from typing import NamedTuple

import einops as op
import jax
from jax import Array
import jax.numpy as jnp

# TODO: eliminate this
d_k = 128

# TODO: Mostly taken from https://github.com/kingoflolz/mesh-transformer-jax/blob/master/mesh_transformer/layers.py
# and https://github.com/huggingface/transformers/blob/main/src/transformers/models/llama/modeling_llama.py#L92
def _make_weights(seq_len: int, d_k: int) -> tuple[Array, Array]:
    inv_freq = 1. / (10000 ** (jnp.arange(0, d_k, 2) / d_k))
    sinusoid_inp = op.einsum(jnp.arange(seq_len), inv_freq, 'L, j -> L j')
    sin_val = jnp.sin(sinusoid_inp)
    cos_val = jnp.cos(sinusoid_inp)
    sin_val = op.repeat(sin_val, 'L K -> L (i K)', i=2)
    cos_val = op.repeat(cos_val, 'L K -> L (i K)', i=2)
    return sin_val, cos_val

def _rotate_half(x: Array) -> Array:
    x = op.rearrange(x, '... (i x) -> ... i x', i=2)  # split the last dimension: (..., n) -> (..., 2, n // 2)
    x = x[..., ::-1, :]  # reverse dimension -2
    x = x.at[..., 0, :].multiply(-1)  # negate the first half of dimension -2
    x = op.rearrange(x, '... i x -> ... (i x)')  # merge the last two dimensions: (..., 2, n // 2) -> (..., n)
    return x

class RotaryValues(NamedTuple):
    sin_val: Array
    cos_val: Array

def forward_rotary_embedding(m: Array, *, rotary_values: RotaryValues) -> Array:
    sin_val, cos_val = rotary_values
    assert sin_val.dtype == jnp.float32
    assert cos_val.dtype == jnp.float32
    n = _rotate_half(m)
    a = op.einsum(m, cos_val, 'B ... L K, B L K -> B ... L K').astype(m.dtype)
    b = op.einsum(n, sin_val, 'B ... L K, B L K -> B ... L K').astype(m.dtype)
    return a + b

def make_rotary_values(padding_len: Array | None, batch_size: int, seq_len: int) -> RotaryValues:
    # sin_val.shape == cos_val.shape == (seq_len 6 ( + 1 every step), d_k 128)
    sin_val, cos_val = _make_weights(seq_len, d_k)

    # sin_val.shape == cos_val.shape == (batch_size 1, seq_len 6 ( + 1 every step), d_k 128)
    sin_val = jnp.repeat(sin_val[None], batch_size, axis=0)
    cos_val = jnp.repeat(cos_val[None], batch_size, axis=0)
    # print('generate')
    # print(sin_val[0,:,0])
    # if padding, then left padding for batch
    if padding_len is not None:
        roll_func = jax.vmap(lambda a, shift: jnp.roll(a, shift, axis=-2))  # -2: dimension L
        sin_val = roll_func(sin_val, - padding_len)
        cos_val = roll_func(cos_val, - padding_len)
        # print(sin_val.shape)
        # print(sin_val[0,:,0])

    return RotaryValues(sin_val, cos_val)

def get_rotary_values_at_position(rotary_values: RotaryValues, position: Array) -> RotaryValues:
    sin_val, cos_val = rotary_values
    # print(f'position:{position}')
    # print(sin_val.shape)
    # print(sin_val[0,:,0])
    sin_val = sin_val[:, position][:, None]
    cos_val = cos_val[:, position][:, None]
    # print(sin_val.shape)
    # print(sin_val[0,:,0])
    rotary_values = RotaryValues(sin_val, cos_val)
    return rotary_values
