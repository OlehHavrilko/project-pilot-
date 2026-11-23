"""Kokoro-ru backend: Russian TTS on GPU (ROCm PyTorch) or CPU.

The model and the acute-aware espeak data are downloaded separately; see
``scripts/fetch_kokoro_assets.py``. On Windows with an AMD GPU install the
ROCm PyTorch wheels (see docs/SETUP.md); the backend picks ``cuda`` automatically.

Known ROCm/Windows quirk: MIOpen's InstanceNorm kernel fails on RDNA4 with
``miopenStatusUnknownError``. The backend replaces ``F.instance_norm`` with a
native mean/variance implementation when running on CUDA, which keeps MIOpen
for the convolutions but avoids the broken kernel.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

from voice.text import split_sentences
from voice.tts import AudioChunk

logger = logging.getLogger(__name__)

REPO = "zaakirio/kokoro-ru"


def _native_instance_norm(input, running_mean=None, running_var=None, weight=None, bias=None,
                          use_input_stats=True, momentum=0.1, eps=1e-5):
    dims = tuple(range(2, input.dim()))
    mean = input.mean(dim=dims, keepdim=True)
    var = input.var(dim=dims, unbiased=False, keepdim=True)
    out = (input - mean) / (var + eps).sqrt()
    if weight is not None:
        out = out * weight.view((1, -1) + (1,) * (input.dim() - 2))
    if bias is not None:
        out = out + bias.view((1, -1) + (1,) * (input.dim() - 2))
    return out


class KokoroBackend:
    def __init__(
        self,
        asset_dir: str | Path,
        voice: str = "sveta",
        device: str = "auto",
        speed: float = 1.0,
        repo: str = REPO,
    ) -> None:
        self.asset_dir = Path(os.path.expandvars(str(asset_dir))).expanduser()
        self.voice_name = voice
        self.name = f"kokoro:{voice}"
        self._device_pref = device
        self._speed = speed
        self._repo = repo
        self._torch = None
        self._model = None
        self._voice = None
        self._g2p = None
        self._warmed = False

    @property
    def device(self) -> str:
        if self._device_pref != "auto":
            return self._device_pref
        if self._torch is not None and self._torch.cuda.is_available():
            return "cuda"
        return "cpu"

    def _load(self) -> None:
        if self._model is not None:
            return
        import torch
        import torch.nn.functional as functional

        if torch.cuda.is_available():
            import torch.nn.modules.instancenorm as instance_norm_module

            functional.instance_norm = _native_instance_norm
            instance_norm_module.F.instance_norm = _native_instance_norm
        from kokoro import KModel

        from voice.third_party.kokoro_ru.ru_g2p import RuG2P

        self._torch = torch
        device = self.device
        model_path = self.asset_dir / "kokoro-ru-v2-base.pth"
        if not model_path.exists():
            raise FileNotFoundError(
                f"Kokoro model not found: {model_path}. Run scripts/fetch_kokoro_assets.py"
            )
        self._model = KModel(repo_id=self._repo, model=model_path).eval().to(device)
        pack_path = self.asset_dir / "voices" / f"{self.voice_name}.pt"
        if not pack_path.exists():
            raise FileNotFoundError(f"Kokoro voice pack not found: {pack_path}")
        self._voice = torch.load(pack_path, map_location="cpu", weights_only=False)
        self._g2p = RuG2P(
            espeak_data=self.asset_dir / "espeak-data",
            vocab_path=self.asset_dir / "kokoro-config.json",
        )
        logger.info("kokoro voice loaded: %s on %s", self.voice_name, device)

    def warmup(self) -> None:
        """Compile kernels and cache allocations so the first real phrase is fast."""
        self._load()
        if self._warmed:
            return
        self._synth("Проверка.")
        self._warmed = True

    def _synth(self, text: str):
        torch = self._torch
        ipa, oov = self._g2p(text)
        if oov:
            logger.warning("unknown phonemes in %r: %s", text[:40], oov)
        if not ipa:
            return None
        style = self._voice[min(len(ipa), 509) - 1]
        style = style.squeeze(0).unsqueeze(0).to(self.device)
        with torch.no_grad():
            audio = self._model(ipa, style, self._speed, return_output=True).audio
        if self.device == "cuda":
            torch.cuda.synchronize()
        return audio.detach().cpu().numpy().reshape(-1)

    def stream(self, text: str):
        if not text.strip():
            return
        self._load()
        import numpy as np

        for sentence in split_sentences(text):
            audio = self._synth(sentence)
            if audio is None or len(audio) == 0:
                continue
            pcm = (np.clip(audio, -1.0, 1.0) * 32767).astype(np.int16).tobytes()
            yield AudioChunk(pcm=pcm, sample_rate=24000, sample_width=2, channels=1)
