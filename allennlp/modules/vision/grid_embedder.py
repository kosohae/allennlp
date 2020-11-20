from typing import Union

import torch
from torch import nn, FloatTensor, IntTensor

from allennlp.common import detectron
from allennlp.common.registrable import Registrable


class GridEmbedder(nn.Module, Registrable):
    """
    A `GridEmbedder` takes a batch of images as a tensor with the dimensions
    (Batch, Color, Height, Width), and returns a tensor in the format
    (Batch, Features, new_height, new_width).

    For every image, it embeds a patch of the image, and returns the embedding
    of the patch. The size of the image might change during this operation.
    """

    def forward(self, images: FloatTensor, sizes: IntTensor) -> FloatTensor:
        raise NotImplementedError()

    def get_output_dim(self) -> int:
        """
        Returns the output dimension that this `GridEmbedder` uses to represent each
        patch. This is `not` the shape of the returned tensor, but the second dimension
        of that shape.
        """
        raise NotImplementedError

    def get_stride(self) -> int:
        """
        Returns the overall stride of this `GridEmbedder`, which, when combined with the input image
        size, will give you the height and width of the output grid.
        """
        raise NotImplementedError


@GridEmbedder.register("null")
class NullGridEmbedder(GridEmbedder):
    """A `GridEmbedder` that returns the input image as given."""

    def forward(self, images: FloatTensor, sizes: IntTensor) -> FloatTensor:
        return images

    def get_output_dim(self) -> int:
        return 3

    def get_stride(self) -> int:
        return 1


@GridEmbedder.register("resnet_backbone")
class ResnetBackbone(GridEmbedder):
    """Runs an image through resnet, as implemented by Detectron."""

    def __init__(
        self,
        meta_architecture: str = "GeneralizedRCNN",
        device: Union[str, int, torch.device] = "cpu",
        weights: str = "RCNN-X152-C4-2020-07-18",
        attribute_on: bool = True,  # not in detectron2 default config
        max_attr_per_ins: int = 16,  # not in detectron2 default config
        stride_in_1x1: bool = False,  # different from default (True)
        num_groups: int = 32,  # different from default (1)
        width_per_group: int = 8,  # different from default (64)
        depth: int = 152,  # different from default (50)
    ):
        super().__init__()
        self.flat_parameters = detectron.DetectronFlatParameters(
            max_attr_per_ins=max_attr_per_ins,
            device=device,
            weights=weights,
            meta_architecture=meta_architecture,
            attribute_on=attribute_on,
            stride_in_1x1=stride_in_1x1,
            num_groups=num_groups,
            width_per_group=width_per_group,
            depth=depth,
        )
        self.register_buffer(
            "pixel_mean", torch.Tensor(self.flat_parameters.pixel_mean).view(-1, 1, 1)
        )
        self.register_buffer(
            "pixel_std", torch.Tensor(self.flat_parameters.pixel_std).view(-1, 1, 1)
        )
        self._backbone = None

    def preprocess(self, images: FloatTensor, sizes: IntTensor) -> FloatTensor:
        # Adapted from https://github.com/facebookresearch/detectron2/blob/
        # 268c90107fba2fea18b1132e5f60532595d771c0/detectron2/modeling/meta_arch/rcnn.py#L224.
        raw_images = [
            (image[:, :height, :width] * 256).byte().to(self.flat_parameters.device)
            for image, (height, width) in zip(images, sizes)
        ]
        standardized = [(x - self.pixel_mean) / self.pixel_std for x in raw_images]
        return detectron.pack_images(standardized, self.backbone.size_divisibility)

    @property
    def backbone(self):
        if self._backbone is None:
            self._backbone = self.flat_parameters.as_config().build_backbone()
        return self._backbone

    def forward(self, images: FloatTensor, sizes: IntTensor) -> FloatTensor:
        images = self.preprocess(images, sizes)
        result = self.backbone(images)
        assert len(result) == 1
        return next(iter(result.values()))

    def get_output_dim(self) -> int:
        return self.backbone.output_shape()["res4"].channels

    def get_stride(self) -> int:
        return self.backbone.output_shape()["res4"].stride
