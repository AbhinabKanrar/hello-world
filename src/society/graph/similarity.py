"""Persona → dense unit feature vectors for homophily.
 
Every attribute becomes an L2-unit *block*, so an attribute with 20 categories carries the
same weight as one with 2. Numeric values are embedded as the unit pair (x, 1-x) so cosine
similarity decays smoothly with distance instead of collapsing to 0/1.
"""

from __future__ import annotations
 
from collections.abc import Sequence
from typing import Any
 
import numpy as np
from numpy.typing import NDArray
 
from society.schemas import DecisionStyle, Persona
 
_TRAIT_WEIGHT = 0.5
_CITY_WEIGHT = 1.0
_STYLES: tuple[DecisionStyle, ...] = tuple(DecisionStyle)
_STYLE_INDEX = {s: i for i, s in enumerate(_STYLES)}


def l2_normalize(x: NDArray[np.float32]) -> NDArray[np.float32]:
    norms = np.linalg.norm(x, axis=1, keepdims=True)
    return (x / np.maximum(norms, 1e-12)).astype(np.float32, copy=False)
 
 
def _is_number(v: Any) -> bool:  # noqa: ANN401
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def _pair(x: NDArray[np.float64]) -> NDArray[np.float32]:
    """Map values in [0,1] to unit vectors (x, 1-x)/‖·‖ — smooth cosine distance."""
    out = np.stack([x, 1.0 - x], axis=1)
    return l2_normalize(out.astype(np.float32))


def _one_hot(labels: Sequence[str]) -> NDArray[np.float32]:
    _, inverse = np.unique(np.asarray(labels, dtype=object), return_inverse=True)
    out = np.zeros((len(labels), int(inverse.max()) + 1 if len(labels) else 0), dtype=np.float32)
    out[np.arange(len(labels)), inverse] = 1.0
    return out


def _multi_hot(rows: Sequence[Sequence[str]]) -> NDArray[np.float32]:
    vocab = {v: i for i, v in enumerate(sorted({v for r in rows for v in r}))}
    out = np.zeros((len(rows), len(vocab)), dtype=np.float32)
    for i, r in enumerate(rows):
        if r:
            out[i, [vocab[v] for v in r]] = 1.0 / np.sqrt(len(r))
    return out


def _encode_attribute(values: Sequence[Any]) -> NDArray[np.float32]:
    if all(_is_number(v) for v in values):
        x = np.asarray(values, dtype=np.float64)
        span = np.ptp(x)
        return _pair((x - x.min()) / span if span > 0 else np.zeros_like(x))
    if all(isinstance(v, list) for v in values):
        return _multi_hot([[str(s) for s in v] for v in values])
    return _one_hot([str(v) for v in values])


def _encode_traits(personas: Sequence[Persona]) -> NDArray[np.float32]:
    style = _one_hot([p.traits.decision_style.value for p in personas])
    ords = np.asarray(
        [(p.traits.openness, p.traits.price_sensitivity, p.traits.skepticism) for p in personas],
        dtype=np.float64,
    )
    scaled = (ords - 1.0) / 4.0
    blocks = [style, _pair(scaled[:, 0]), _pair(scaled[:, 1]), _pair(scaled[:, 2])]
    return np.hstack(blocks) / 2.0  # four unit sub-blocks → overall unit norm


class FeatureEncoder:
    __slots__ = ()
 
    def transform(self, personas: Sequence[Persona]) -> NDArray[np.float32]:
        n = len(personas)
        if n == 0:
            return np.zeros((0, 0), dtype=np.float32)
        blocks: list[NDArray[np.float32]] = [
            _encode_attribute([p.attributes.get(key) for p in personas])
            for key in personas[0].attributes
        ]

        blocks.append(_encode_traits(personas) * _TRAIT_WEIGHT)
        if any(p.profile is not None for p in personas):
            cities = [p.profile.city if p.profile else "" for p in personas]
            blocks.append(_one_hot(cities) * _CITY_WEIGHT)
        return np.hstack(blocks)
