# Person B — Day4: U-Net 模型与训练脚本

## Goals (规划.docx)

Person B Day4: **U-Net 模型搭建、训练脚本**。

## Implemented

| Module | Role |
|--------|------|
| `ai/models/unet.py` | 2D U-Net（encoder-decoder + skip connections） |
| `ai/loss.py` | Dice Loss + BCE Loss 加权组合 |
| `ai/train.py` | 完整训练 / 验证 / 测试循环，保存 best checkpoint |

## 模型设计参考

### 1. 整体结构（U-Net, Ronneberger et al.）

本项目的 `UNet2D` 采用经典 **编码器-解码器 + 跳跃连接** 结构，输入单通道 CT 切片，输出单通道分割 logits。

```text
Input [B,1,256,256]
    |
    v
+-----------+     skip x1 [B, 64,256,256]
|  in_conv  | --------------------------------------+
+-----------+                                       |
    | maxpool                                       |
    v                                               |
+-----------+     skip x2 [B,128,128,128]           |
|  down1    | -----------------------------+        |
+-----------+                              |        |
    |                                      |        |
    v                                      |        |
+-----------+     skip x3 [B,256, 64, 64]   |        |
|  down2    | --------------------+        |        |
+-----------+                       |        |        |
    |                               |        |        |
    v                               |        |        |
+-----------+     skip x4 [B,512, 32, 32]   |        |
|  down3    | -----------+          |        |        |
+-----------+              |          |        |        |
    |                      |          |        |        |
    v                      |          |        |        |
+-----------+              |          |        |        |
| bottleneck| [B,1024,16,16]         |        |        |
+-----------+              |          |        |        |
    | upsample+concat       |          |        |        |
    v                      |          |        |        |
+-----------+              |          |        |        |
|   up1     | <------------+          |        |        |
+-----------+                         |        |        |
    v                                 |        |        |
+-----------+                         |        |        |
|   up2     | <-----------------------+        |        |
+-----------+                                    |        |
    v                                            |        |
+-----------+                                    |        |
|   up3     | <----------------------------------+        |
+-----------+                                             |
    v                                                     |
+-----------+                                             |
|   up4     | <-------------------------------------------+
+-----------+
    |
    v
 out_conv 1x1 -> [B,1,256,256] logits
```

### 2. 参考代码：DoubleConv 基本块

这是 U-Net 中最常用的重复单元，相当于论文中的两层 3×3 卷积：

```python
class DoubleConv(nn.Module):
    def __init__(self, in_channels, out_channels):
        super().__init__()
        self.block = nn.Sequential(
            nn.Conv2d(in_channels, out_channels, 3, padding=1, bias=False),
            nn.BatchNorm2d(out_channels),
            nn.ReLU(inplace=True),
            nn.Conv2d(out_channels, out_channels, 3, padding=1, bias=False),
            nn.BatchNorm2d(out_channels),
            nn.ReLU(inplace=True),
        )

    def forward(self, x):
        return self.block(x)
```

**设计要点：**
- `3×3` 卷积 + `padding=1` 保持空间尺寸不变
- `BatchNorm` 稳定小 batch 训练
- 每层两次卷积，增大感受野

### 3. 通道数设计（base_channels=64）

| Stage | 模块 | 输出通道 | 空间尺寸 (256 输入) |
|-------|------|----------|---------------------|
| 0 | in_conv | 64 | 256×256 |
| 1 | down1 | 128 | 128×128 |
| 2 | down2 | 256 | 64×64 |
| 3 | down3 | 512 | 32×32 |
| 4 | bottleneck | 1024 | 16×16 |
| 5–8 | up1–up4 | 512→64 | 恢复至 256×256 |
| out | out_conv | 1 | 256×256 |

参数量约 **31M**（`base_channels=64` 时）。样本较少时可改为 `base_channels=32` 减轻过拟合。

### 4. 损失函数参考

分割任务常用 **Dice + BCE** 组合：

```python
def combined_loss(pred, target, dice_weight=0.5, bce_weight=0.5):
    dice = 1 - (2 * (sigmoid(pred) * target).sum() + 1e-6) / (sigmoid(pred).sum() + target.sum() + 1e-6)
    bce = F.binary_cross_entropy_with_logits(pred, target)
    return dice_weight * dice + bce_weight * bce
```

| 损失 | 作用 |
|------|------|
| Dice Loss | 直接优化区域重叠，适合小目标（肺结节） |
| BCE Loss | 稳定像素级分类，防止 Dice 梯度不稳定 |

### 5. 训练配置（`ai/config.py`）

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `MODEL_ARCH` | `unet_2d` | 模型类型 |
| `IN_CHANNELS` / `OUT_CHANNELS` | 1 / 1 | 灰度输入 + 二值 mask |
| `UNET_BASE_CHANNELS` | 64 | 首层通道数 |
| `EPOCHS` | 50 | 最大 epoch |
| `BATCH_SIZE` | 8 | DataLoader batch |
| `LEARNING_RATE` | 1e-4 | Adam 学习率 |
| `LOSS_DICE_WEIGHT` | 0.5 | Dice 权重 |
| `LOSS_BCE_WEIGHT` | 0.5 | BCE 权重 |
| `EARLY_STOP_PATIENCE` | 10 | val Dice 无提升则早停 |

### 6. 与其他分割模型对比（扩展参考）

| 模型 | 特点 | 适用场景 |
|------|------|----------|
| **U-Net 2D**（本项目） | 结构简单、训练快、易联调 | 单切片 2D 结节分割 |
| U-Net 3D | 利用体数据上下文 | 整卷 CT 分割 |
| Attention U-Net | 注意力门控 skip | 小目标、边界 refinement |
| nnU-Net | 自适应预处理 + 3D U-Net | 竞赛级 baseline |

Day4 先完成 2D U-Net；Day7 可在此基础上替换为 Attention U-Net 做对比实验。

## 运行

```bash
# 确保已有 Day2 数据
python scripts/convert_lung_examples.py --lung-root /path/to/Lung

# 训练（默认 50 epoch，可用 --epochs 5 快速试跑）
python ai/train.py
python ai/train.py --epochs 5
```

## 输出

| 路径 | 内容 |
|------|------|
| `ai/checkpoints/Model0001.pt` | best val Dice 对应的权重 |
| `ai/runs/{timestamp}/metrics.json` | 每 epoch loss/dice/iou 记录 |

Checkpoint 结构：

```json
{
  "model_id": "Model0001",
  "model_arch": "unet_2d",
  "epoch": 12,
  "best_val_dice": 0.85,
  "model_state_dict": "...",
  "config": { "base_channels": 64, "learning_rate": 0.0001 }
}
```

## Day5 已完成

见 [11_person_b_day5.md](11_person_b_day5.md)：多切片数据扩充 + 50 epoch 完整训练，产出 `Model0001.pt`。
