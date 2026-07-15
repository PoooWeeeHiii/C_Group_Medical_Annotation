# DeepEdit weights (local only)

Do **not** commit `*.pth` / `*.ts` here.

## Target organs

Binary interactive edit (4-in / 2-out) trained on mixed masks:

- `heart`
- `liver`
- `spleen`
- `left_lung` / `right_lung`
- `left_kidney` / `right_kidney`

## Files

| File | Role |
|------|------|
| `config.json` | Loaded by `ai/deepedit_service.py` |
| `deepedit_unet.pth` | MONAI UNet checkpoint (train output) |
| `deepedit_unet.train_meta.json` | Epoch / Dice log |

## Person B commands

```powershell
# 1) Build dataset (spleen from MSD; optional TotalSeg pseudo for 5 organs)
D:\anaconda\python.exe -u scripts\prepare_deepedit_organs.py --from-msd-spleen --limit 20
# D:\anaconda\python.exe -u scripts\prepare_deepedit_organs.py --from-msd-spleen --from-totalseg-pseudo --limit 5

# 2) Smoke train (writes deepedit_unet.pth)
D:\anaconda\python.exe -u scripts\train_deepedit.py --smoke

# 2b) Multi-organ pseudo labels (TotalSeg) then full train
D:\anaconda\python.exe -u scripts\prepare_deepedit_organs.py --from-msd-spleen --from-totalseg-pseudo --limit 8
D:\anaconda\python.exe -u scripts\train_deepedit.py --epochs 50 --batch-size 1 --spatial-size 64 128 128
# Interrupted? resume:
# D:\anaconda\python.exe -u scripts\train_deepedit.py --epochs 50 --resume

# 3) Longer train
D:\anaconda\python.exe -u scripts\train_deepedit.py --epochs 50 --batch-size 1

# 4) Start service (:8010)
powershell -ExecutionPolicy Bypass -File scripts\start_deepedit.ps1
curl http://127.0.0.1:8010/health
```

Data root default: `E:\lxy\hm_2_deepedit\dataset`
