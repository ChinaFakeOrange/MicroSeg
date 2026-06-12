"""Segmentation model factory.

The original project hand-rolled an EfficientNetV2 + attention U-Net (~700 lines).
For an open-source, maintainable codebase we build on ``segmentation-models-pytorch``
(already a project dependency), which provides the same EfficientNet-encoder +
U-Net-decoder design with pretrained ImageNet weights and far less code to audit.
The three original size tiers (轻量级/中量级/高量级) map onto EfficientNet variants.
"""
from __future__ import annotations

from typing import Dict

SIZE_TO_ENCODER: Dict[str, str] = {
    "light": "efficientnet-b0",     # 轻量级
    "medium": "efficientnet-b3",    # 中量级
    "heavy": "efficientnet-b5",     # 高量级
}

# Accept the original Chinese labels too, for a smooth migration.
ALIASES = {"轻量级": "light", "中量级": "medium", "高量级": "heavy"}


def build_segmentation_model(num_classes: int, size: str = "medium", in_channels: int = 3):
    """Create a U-Net with an EfficientNet encoder.

    Parameters
    ----------
    num_classes: number of output classes (including background).
    size: ``light`` | ``medium`` | ``heavy`` (or the original Chinese labels).
    in_channels: input channels (3 for RGB microscopy).
    """
    import segmentation_models_pytorch as smp

    size = ALIASES.get(size, size)
    encoder = SIZE_TO_ENCODER.get(size, SIZE_TO_ENCODER["medium"])
    model = smp.Unet(
        encoder_name=encoder,
        encoder_weights="imagenet",
        in_channels=in_channels,
        classes=num_classes,
        decoder_attention_type="scse",   # spatial+channel attention, mirrors the
                                         # AttentionBlock in the original decoder
    )
    return model
