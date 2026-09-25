from typing import Iterable


def indices_to_mask(indices: Iterable[int]) -> int:
    mask = 0
    for index in set(indices):
        mask |= 1 << index
    return mask


def mask_to_indices(mask: int) -> list[int]:
    return [index for index in range(mask.bit_length()) if (mask >> index) & 1]
