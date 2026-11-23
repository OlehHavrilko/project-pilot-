# Third-party: Russian G2P for Kokoro

`ru_g2p.py` is copied from <https://huggingface.co/zaakirio/kokoro-ru> (file `ru_g2p.py`).
The model card states: weights are OpenRAIL, code is Apache-2.0.
Only one change is applied: explicit `encoding="utf-8"` when reading `kokoro-config.json`,
because Windows Python defaults to cp1251 and fails to decode the file.
