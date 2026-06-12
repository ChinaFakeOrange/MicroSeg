"""Semantic segmentation training.

Reports per-epoch progress to the :class:`TaskTracker` and honours cooperative
cancellation. Replaces the old subprocess + stdout-scraping approach: training
runs inside a Celery worker, progress is structured, and the best checkpoint is
saved into the project's ``models/`` directory.
"""
from __future__ import annotations

import random
from pathlib import Path
from typing import Dict, List, Tuple

import numpy as np
from PIL import Image

from app.config import get_settings
from app.core.storage import store
from app.core.tasks import TaskState, tracker
from app.ml.models.efficientnet_unet import build_segmentation_model
from app.ml.models.losses import ComboLoss, dice_score


def _list_pairs(project_id: str, image_ids=None, include_extra: bool = True) -> List[Tuple[Path, Path]]:
    """Collect (image, mask) training pairs.

    image_ids: if given, only project images whose id is in this set are used
               (lets the user hand-pick the training set). None = all masked.
    include_extra: also append externally-uploaded image+mask pairs.
    """
    pairs = []
    want = set(image_ids) if image_ids else None
    for entry in store.list_images(project_id):
        if want is not None and entry["id"] not in want:
            continue
        img = store.image_path(project_id, entry["id"])
        mask = store.mask_path(project_id, entry["id"])
        if img and mask.exists():
            pairs.append((img, mask))
    if include_extra:
        for ip, mp in store.extra_pair_paths(project_id):
            if ip.exists() and mp.exists():
                pairs.append((ip, mp))
    return pairs


def train_segmentation(task_id: str, project_id: str, params: Dict) -> Dict:
    import torch
    from torch.utils.data import DataLoader, Dataset

    settings = get_settings()
    device = torch.device(settings.resolve_device())
    project = store.get(project_id)
    num_classes = len(project.classes) + 1  # + background
    epochs = int(params.get("epochs", 50))
    batch_size = int(params.get("batch_size", 8))
    lr = float(params.get("lr", 1e-3))
    input_size = int(params.get("input_size", 512))
    size = params.get("model_size", "medium")
    # --- dataset customization ---
    image_ids = params.get("image_ids")                 # hand-picked subset (None = all)
    include_extra = params.get("include_extra", True)    # also use uploaded external pairs
    val_fraction = float(params.get("val_fraction", 0.15))
    seed = int(params.get("seed", 42))
    aug = params.get("augment", {}) or {}
    aug_hflip = bool(aug.get("hflip", True))
    aug_vflip = bool(aug.get("vflip", False))
    aug_rot90 = bool(aug.get("rot90", False))
    aug_bright = bool(aug.get("brightness", False))

    pairs = _list_pairs(project_id, image_ids=image_ids, include_extra=include_extra)
    if not pairs:
        raise ValueError("No image/mask pairs found. Save some masks (or upload external pairs) first.")
    # Shuffle deterministically, then split off a validation fraction.
    rng = random.Random(seed)
    pairs = pairs[:]
    rng.shuffle(pairs)
    val_fraction = min(0.5, max(0.0, val_fraction))
    n_val = int(round(len(pairs) * val_fraction))
    val_pairs = pairs[:n_val]
    train_pairs = pairs[n_val:] or pairs[:1]
    if not val_pairs:
        val_pairs = train_pairs[:1]

    class SegDataset(Dataset):
        def __init__(self, items, train: bool):
            self.items = items
            self.train = train

        def __len__(self):
            return len(self.items)

        def __getitem__(self, i):
            img_p, mask_p = self.items[i]
            img = Image.open(img_p).convert("RGB").resize((input_size, input_size))
            mask = Image.open(mask_p).resize((input_size, input_size), Image.NEAREST)
            x = np.asarray(img, dtype=np.float32) / 255.0
            y = np.asarray(mask, dtype=np.int64)
            if y.ndim == 3:
                y = y[..., 0]
            if self.train:
                if aug_hflip and np.random.rand() < 0.5:
                    x, y = x[:, ::-1].copy(), y[:, ::-1].copy()
                if aug_vflip and np.random.rand() < 0.5:
                    x, y = x[::-1, :].copy(), y[::-1, :].copy()
                if aug_rot90 and np.random.rand() < 0.5:
                    k = np.random.randint(1, 4)
                    x, y = np.rot90(x, k).copy(), np.rot90(y, k).copy()
                if aug_bright and np.random.rand() < 0.5:
                    factor = 1.0 + (np.random.rand() - 0.5) * 0.4   # ±20%
                    x = np.clip(x * factor, 0.0, 1.0)
            x = torch.from_numpy(x).permute(2, 0, 1)
            y = torch.from_numpy(y)
            return x, y

    # num_workers must be 0: the Celery prefork worker is itself a daemon
    # process, and daemonic processes are not allowed to spawn children.
    train_loader = DataLoader(SegDataset(train_pairs, True), batch_size=batch_size, shuffle=True, num_workers=0)
    val_loader = DataLoader(SegDataset(val_pairs, False), batch_size=batch_size, num_workers=0)

    model = build_segmentation_model(num_classes, size=size).to(device)

    # Continue training from an existing checkpoint when requested.
    resume = params.get("resume_model")
    if resume:
        ckpt_path = store.models_dir(project_id) / resume
        if ckpt_path.exists():
            ckpt = torch.load(ckpt_path, map_location=device)
            if ckpt.get("num_classes") == num_classes:
                model.load_state_dict(ckpt["state_dict"])
                tracker.update(task_id, message=f"Resuming from {resume}")
            else:
                raise ValueError(
                    f"Cannot resume {resume}: it has {ckpt.get('num_classes')} classes "
                    f"but this project now has {num_classes}.")
        else:
            raise ValueError(f"Checkpoint {resume} not found.")

    optimizer = torch.optim.AdamW(model.parameters(), lr=lr)
    scheduler = torch.optim.lr_scheduler.OneCycleLR(
        optimizer, max_lr=lr, steps_per_epoch=max(1, len(train_loader)), epochs=epochs, pct_start=0.1
    )
    criterion = ComboLoss()
    scaler = torch.cuda.amp.GradScaler(enabled=device.type == "cuda")

    best_dice = -1.0
    ckpt_dir = store.path(project_id) / "models"
    ckpt_dir.mkdir(exist_ok=True)
    best_path = ckpt_dir / f"seg_{task_id[:8]}_best.pt"
    history = []

    for epoch in range(1, epochs + 1):
        if tracker.is_cancelled(task_id):
            raise InterruptedError("cancelled")

        model.train()
        running = 0.0
        for x, y in train_loader:
            x, y = x.to(device), y.to(device)
            optimizer.zero_grad()
            with torch.autocast(device_type=device.type, enabled=device.type == "cuda"):
                out = model(x)
                loss = criterion(out, y)
            scaler.scale(loss).backward()
            scaler.step(optimizer)
            scaler.update()
            scheduler.step()
            running += loss.item()

        model.eval()
        val_dice = 0.0
        with torch.no_grad():
            for x, y in val_loader:
                x, y = x.to(device), y.to(device)
                out = model(x)
                val_dice += dice_score(out, y)
        val_dice /= max(1, len(val_loader))
        train_loss = running / max(1, len(train_loader))
        history.append({"epoch": epoch, "train_loss": train_loss, "val_dice": val_dice})

        if val_dice > best_dice:
            best_dice = val_dice
            torch.save({"state_dict": model.state_dict(), "num_classes": num_classes,
                        "size": size, "input_size": input_size}, best_path)

        tracker.update(
            task_id, progress=epoch / epochs,
            message=f"Epoch {epoch}/{epochs} · loss {train_loss:.3f} · dice {val_dice:.3f}",
        )

    return {"best_dice": best_dice, "checkpoint": best_path.name, "history": history,
            "n_pairs": len(pairs), "n_train": len(train_pairs), "n_val": len(val_pairs),
            "n_extra": len(store.extra_pair_paths(project_id)) if include_extra else 0,
            "val_fraction": val_fraction, "seed": seed}
