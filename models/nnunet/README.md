# Packaged nnUNet checkpoints (Person B)

Large `checkpoint_best.pth` files are stored with **Git LFS**.

```text
models/nnunet/
  Dataset506_Spleen/nnUNetTrainer_100epochs__nnUNetPlans__3d_fullres/
  Dataset510_DeepEdit_Heart/...
  Dataset511_DeepEdit_Liver/...
  Dataset512_DeepEdit_Lung/...
  Dataset513_DeepEdit_Kidney/...
```

After clone:

```powershell
git lfs install
git lfs pull
```

Optional `.env` (defaults can point here):

```env
SPLEEN_MODEL_DIR=models/nnunet/Dataset506_Spleen/nnUNetTrainer_100epochs__nnUNetPlans__3d_fullres
ORGANS_NNUNET_RESULTS=models/nnunet
```

Note: `ORGANS_NNUNET_RESULTS` layout must match `Dataset51x_.../nnUNetTrainer_...` as above.
