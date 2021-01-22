# Copyright 2020 Adap GmbH. All Rights Reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
# ==============================================================================
"""PyTorch CIFAR-10/100 image classification."""

# mypy: ignore-errors
# pylint: disable=W0223

import argparse
from os import PathLike
from pathlib import Path
from typing import List, Optional, Tuple, Union

import numpy as np
import torch.nn as nn
from torch import Tensor, from_numpy, load, save
from torch.utils.data import Dataset
from torchvision.datasets import CIFAR10, CIFAR100
from torchvision.transforms import Compose, Normalize, ToTensor

import flwr as fl
from flwr.dataset.utils.common import XY, XYList, create_lda_partitions
from flwr_experimental.baseline.pytorch.utils import convert_pytorch_dataset_to_xy

DATA_ROOT: str = "~/.flower/data/cifar"


def get_normalization_transform() -> Compose:
    """Generates a compose transformation with mean and average normalization
    for CIFAR10.

    Returns:
        transforms.transforms.Compose: A Compose transformation for CIFAR10
    """
    transform = Compose(
        [
            ToTensor(),
            Normalize((0.4914, 0.4822, 0.4465), (0.2023, 0.1994, 0.2010)),
        ]
    )
    return transform


class CIFAR_PartitionedDataset(Dataset):
    def __init__(
        self,
        *,
        num_classes: int = 10,
        root_dir: Union[str, bytes, PathLike] = DATA_ROOT,
        partition_id: int,
        transform: Optional[callable],
    ):
        """Dataset from partitioned files
        Parameters
        ----------
        num_classes: int
            Defines which dataset to use. CIFAR10 or CIFAR100.
        partition_id : int
            Partition file ID. Usually the same as the client ID.
        root_dir : Union[str, bytes, os.PathLike]
            Directory containing partioned files.
        """

        if num_classes not in [10, 100]:
            raise ValueError(
                """Number of classes can only be either 
                10 or 100 for CIFAR10 and CIFAR100 datasets respectively."""
            )
        self.root_dir: Path = Path(root_dir)
        self.partition_id: int = partition_id
        self.partition_path = (
            self.root_dir / f"cifar{num_classes}_{self.partition_id}.pt"
        )

        if not self.partition_path.exists():
            raise RuntimeError(f"Partition file {self.partition_path} not found.")
        else:
            self.X, self.Y = load(self.partition_path)
            self.X = from_numpy(self.X)
            self.Y = from_numpy(self.Y)

    def __len__(self) -> int:
        return len(self.X)

    def __getitem__(self, idx: int) -> XY:
        x = self.X[idx]
        y = self.Y[idx]

        if self.transform:
            x = self.trasform(x)

        return (x, y)


class CIFAR10PartitionedDataset(CIFAR_PartitionedDataset):
    """Augmented and partitioned dataset based on CIFAR10."""

    def __init__(
        self,
        *,
        root_dir: Union[str, bytes, PathLike] = DATA_ROOT,
        partition_id: int,
    ):
        """Dataset from partitioned files
        Parameters
        ----------
        partition_id : int
            Partition file ID. Usually the same as the client ID.
        root_dir : Union[str, bytes, os.PathLike]
            Directory containing partioned files.
        """
        super().__init__(num_classes=10, root_dir=root_dir, partition_id=partition_id)


class CIFAR100PartitionedDataset(CIFAR_PartitionedDataset):
    """Augmented and partitioned dataset based on CIFAR10."""

    def __init__(
        self,
        *,
        root_dir: Union[str, bytes, PathLike] = DATA_ROOT,
        partition_id: int,
    ):
        """Dataset from partitioned files
        Parameters
        ----------
        partition_id : int
            Partition file ID. Usually the same as the client ID.
        root_dir : Union[str, bytes, os.PathLike]
            Directory containing partioned files.
        """
        super().__init__(num_classes=100, root_dir=root_dir, partition_id=partition_id)


if __name__ == "__main__":
    """Generates Latent Dirichlet Allocated Partitions for CIFAR10/100
    datasets."""
    parser = argparse.ArgumentParser(
        description="Generate Latent Dirichlet Allocated Partitions for CIFAR10/100 datasets."
    )

    parser.add_argument(
        "--num_classes",
        type=int,
        required=True,
        choices=[10, 100],
        help="Choose 10 for CIFAR10 and 100 for CIFAR100.",
    )
    parser.add_argument(
        "--num_partitions",
        type=int,
        default=500,
        help="Number of partitions in which to split the dataset.",
    )
    parser.add_argument(
        "--alpha",
        type=float,
        default=0.1,
        help="Choose Dirichlet concentration.",
    )
    parser.add_argument(
        "--save_root",
        type=str,
        default=DATA_ROOT,
        help="Choose where to save partition.",
    )

    args = parser.parse_args()
    save_root = Path(f"{args.save_root}") / "partitions" / "lda" / f"{args.alpha:.2f}"

    # Use standard mean and standard variation
    basic_transform = get_normalization_transform()

    train_dataset = CIFAR10(
        root=f"{DATA_ROOT}-{args.num_classes}",
        train=True,
        download=True,
    )
    test_dataset = CIFAR10(
        root=f"{DATA_ROOT}-{args.num_classes}",
        train=True,
        download=True,
    )
    dist = np.empty(0)
    for dataset, data_str in [(train_dataset, "train"), (test_dataset, "test")]:
        save_dir = save_root / data_str
        save_dir.mkdir(parents=True, exist_ok=True)

        np_dataset = convert_pytorch_dataset_to_xy(dataset)

        partitions, dist = create_lda_partitions(
            dataset=np_dataset,
            dirichlet_dist=dist,
            num_partitions=args.num_partitions,
            concentration=args.alpha,
        )

        for idx, part in enumerate(partitions):
            save(part, save_dir / f"{idx:03}.pt")