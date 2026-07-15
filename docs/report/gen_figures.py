import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib import font_manager
from matplotlib.patches import FancyBboxPatch, Rectangle, Ellipse
from pathlib import Path

# Prefer a CJK-capable font so Chinese labels render correctly on macOS.
for _fname in (
    'Songti SC',
    'Hiragino Sans GB',
    'Heiti SC',
    'Arial Unicode MS',
    'PingFang SC',
):
    try:
        path = font_manager.findfont(_fname, fallback_to_default=False)
        if path and 'DejaVu' not in path:
            plt.rcParams['font.family'] = _fname
            plt.rcParams['axes.unicode_minus'] = False
            break
    except Exception:
        continue

fig_dir = Path(__file__).resolve().parent / 'figures'
fig_dir.mkdir(parents=True, exist_ok=True)

def save(fig, name):
    fig.savefig(fig_dir / name, dpi=160, bbox_inches='tight', facecolor='white')
    plt.close(fig)
    print('wrote', name)

fig, ax = plt.subplots(figsize=(11, 6.2))
ax.set_xlim(0, 11); ax.set_ylim(0, 6.5); ax.axis('off')
ax.set_title('Figure 1 / 图1  C组医学标注平台总体架构', fontsize=13, pad=12)
layers = [
    (0.4, 5.2, 10.2, 1.0, '#E8F1FA', '表现层 Presentation\nFrontend (app.js / volume_viewer.js / hand_gesture.js)  ·  React web  ·  VTK / WebGL2 / MediaPipe'),
    (0.4, 3.7, 10.2, 1.0, '#EAF6EA', '接口层 API\nFastAPI  /api/*  · Auth JWT  · Cases/Images/Masks/Versions  · AI Predict  · Surgery Results  · Export'),
    (0.4, 2.2, 4.8, 1.0, '#FFF6E5', '业务服务 Services\nmask / volume / workflow\nsurgery / ai_service'),
    (5.6, 2.2, 5.0, 1.0, '#F5EAF6', 'AI 对接\nnnUNet / TotalSeg / DeepEdit\nplatform_unet predict'),
    (0.4, 0.7, 4.8, 1.0, '#F0F0F0', '数据层 Data\nSQLite · schema.sql\nsurgery_results / masks'),
    (5.6, 0.7, 5.0, 1.0, '#F0F0F0', '存储 Storage\ndataset/ · DICOM/NIfTI\nmask 文件与导出 Dataset'),
]
for x,y,w,h,c,t in layers:
    ax.add_patch(FancyBboxPatch((x,y), w,h, boxstyle='round,pad=0.03,rounding_size=0.08',
                                facecolor=c, edgecolor='#334', linewidth=1.2))
    ax.text(x+w/2, y+h/2, t, ha='center', va='center', fontsize=8.5)
save(fig, 'fig1_architecture.png')

fig, ax = plt.subplots(figsize=(10, 6.5))
ax.set_xlim(0,10); ax.set_ylim(0,7); ax.axis('off')
ax.set_title('Figure 2 / 图2  核心用例（围绕本人平台侧）', fontsize=13, pad=10)
for name,y in [('标注员 Annotator',5.5),('审核员 Reviewer',3.5),('管理员 Admin',1.5)]:
    ax.add_patch(Ellipse((1.2,y), 1.6, 0.9, facecolor='#DDEEFF', edgecolor='#234'))
    ax.text(1.2,y, name, ha='center', va='center', fontsize=8)
ax.add_patch(Rectangle((3.0,0.4), 6.5, 6.2, fill=False, edgecolor='#234', linewidth=1.5))
ax.text(6.25, 6.35, '医学影像标注平台', ha='center', fontsize=10, fontweight='bold')
usecases = [
    (5.0,5.8,'登录与权限控制'),(7.6,5.8,'上传 CT / DICOM'),
    (5.0,4.7,'2D 多标签标注'),(7.6,4.7,'版本保存与对比'),
    (5.0,3.6,'3D/MPR 可视化'),(7.6,3.6,'手势交互选器官'),
    (5.0,2.5,'调用 AI 预测'),(7.6,2.5,'模拟手术 ROI 入库'),
    (5.0,1.4,'任务分配审核'),(7.6,1.4,'导出训练 Dataset'),
]
for x,y,t in usecases:
    ax.add_patch(Ellipse((x,y), 2.2, 0.7, facecolor='#FFF8E7', edgecolor='#444'))
    ax.text(x,y,t, ha='center', va='center', fontsize=7.5)
for y in [5.5,3.5,1.5]:
    ax.annotate('', xy=(3.9, min(y,5.8)), xytext=(2.0,y),
                arrowprops=dict(arrowstyle='-', color='#666', lw=0.8))
save(fig, 'fig2_usecase.png')

fig, ax = plt.subplots(figsize=(11, 3.8))
ax.set_xlim(0,11); ax.set_ylim(0,3.2); ax.axis('off')
ax.set_title('Figure 3 / 图3  标注主流程', fontsize=13, pad=8)
steps = ['上传影像','病例入库','2D/3D浏览','人工/AI标注','版本评审','导出Dataset']
for i,s in enumerate(steps):
    x=0.4+i*1.8
    ax.add_patch(FancyBboxPatch((x,1.2), 1.5, 0.9, boxstyle='round,pad=0.02',
                                facecolor='#E7F0FF', edgecolor='#234'))
    ax.text(x+0.75, 1.65, s, ha='center', va='center', fontsize=9)
    if i<len(steps)-1:
        ax.annotate('', xy=(x+1.7,1.65), xytext=(x+1.5,1.65),
                    arrowprops=dict(arrowstyle='->', color='#234', lw=1.4))
ax.text(5.5, 0.5, '人机协同：AI 粗标 → 人工精修 → 审核闭环 → 可训练数据产出', ha='center', fontsize=9, color='#333')
save(fig, 'fig3_annotation_flow.png')

fig, ax = plt.subplots(figsize=(11, 3.6))
ax.set_xlim(0,11); ax.set_ylim(0,3); ax.axis('off')
ax.set_title('Figure 4 / 图4  模拟手术 ROI 三步流程', fontsize=13, pad=8)
steps = ['选中目标器官','确认长方体 ROI','切割并保存结果']
colors = ['#E8F7E8','#FFF3D6','#FFE5E5']
for i,(s,c) in enumerate(zip(steps,colors)):
    x=0.8+i*3.3
    ax.add_patch(FancyBboxPatch((x,1.1), 2.8, 1.0, boxstyle='round,pad=0.03',
                                facecolor=c, edgecolor='#333'))
    ax.text(x+1.4, 1.6, f'Step {i+1}\n{s}', ha='center', va='center', fontsize=10)
    if i<2:
        ax.annotate('', xy=(x+3.15,1.6), xytext=(x+2.8,1.6),
                    arrowprops=dict(arrowstyle='->', color='#333', lw=1.5))
ax.text(5.5, 0.4, '入库字段含 organ_name / display_name / color + 多面体切面 cut_planes', ha='center', fontsize=8.5)
save(fig, 'fig4_surgery_flow.png')

fig, ax = plt.subplots(figsize=(10.5, 5.8))
ax.set_xlim(0,10.5); ax.set_ylim(0,6); ax.axis('off')
ax.set_title('Figure 5 / 图5  核心数据实体关系（节选）', fontsize=13, pad=10)
boxes = [
    (0.4,4.2,'cases\ncase_id, patient_id, status'),
    (3.6,4.2,'images\nimage_id, case_id, path'),
    (6.8,4.2,'masks\nmask_id, image_id, label_id'),
    (0.4,2.0,'versions\nversion_id, case_id, mask_id'),
    (3.6,2.0,'users / tasks\nrole, assignee, deadline'),
    (6.8,2.0,'surgery_results\nresult_id, organ_*, ROI'),
]
for x,y,t in boxes:
    ax.add_patch(FancyBboxPatch((x,y), 2.8, 1.3, boxstyle='round,pad=0.03',
                                facecolor='#F7F7F7', edgecolor='#222'))
    ax.text(x+1.4, y+0.65, t, ha='center', va='center', fontsize=8)
for a,b in [((3.2,4.85),(3.6,4.85)), ((6.4,4.85),(6.8,4.85)),
            ((1.8,4.2),(1.8,3.3)), ((5.0,4.2),(5.0,3.3)), ((8.2,4.2),(8.2,3.3))]:
    ax.annotate('', xy=b, xytext=a, arrowprops=dict(arrowstyle='->', color='#555', lw=1))
ax.text(5.25, 0.6, '说明：surgery_results 记录模拟手术 ROI，并冗余保存选中器官名称与颜色，便于回溯。', ha='center', fontsize=8.5)
save(fig, 'fig5_er.png')

fig, ax = plt.subplots(figsize=(10.5, 5.5))
ax.set_xlim(0,10.5); ax.set_ylim(0,5.5); ax.axis('off')
ax.set_title('Figure 6 / 图6  保存手术 ROI 时序（简化）', fontsize=13, pad=10)
actors=['前端 Viewer','app.js','API /surgery','surgery_service','SQLite']
xs=[1.0,3.0,5.2,7.2,9.2]
for x,a in zip(xs,actors):
    ax.text(x, 5.1, a, ha='center', fontsize=8, fontweight='bold')
    ax.plot([x,x],[0.4,4.85], color='#aaa', lw=1, ls='--')
msgs=[
    (0,1,4.5,'getSurgerySnapshot()'),
    (1,2,3.8,'POST /api/surgery_results'),
    (2,3,3.1,'校验 + 解析 organ'),
    (3,4,2.4,'INSERT surgery_results'),
    (4,3,1.7,'row'),
    (3,2,1.2,'SaveSurgeryResultResponse'),
    (2,1,0.7,'toast: 已入库'),
]
for i,j,y,t in msgs:
    ax.annotate('', xy=(xs[j],y), xytext=(xs[i],y),
                arrowprops=dict(arrowstyle='->', color='#234', lw=1.2))
    ax.text((xs[i]+xs[j])/2, y+0.12, t, ha='center', fontsize=7.5)
save(fig, 'fig6_sequence.png')

fig, ax = plt.subplots(figsize=(10, 2.2))
ax.set_xlim(0,10); ax.set_ylim(0,2.2); ax.axis('off')
ax.add_patch(FancyBboxPatch((0.3,0.3), 9.4, 1.6, boxstyle='round,pad=0.04',
                            facecolor='#FAFAFA', edgecolor='#888', linestyle='--', linewidth=1.5))
ax.text(5, 1.3, '【运行界面截图预留位】', ha='center', fontsize=14, color='#555')
ax.text(5, 0.75, '请在定稿时替换为本地实际界面（登录 / 标注台 / 3D手势 / 手术ROI）', ha='center', fontsize=9, color='#777')
save(fig, 'fig_placeholder_ui.png')
print('all figures done')
