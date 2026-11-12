import importlib.util
import sys
from pathlib import Path

import torch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
spec = importlib.util.spec_from_file_location("train_v5", ROOT / "scripts/train_v5.py")
train_v5 = importlib.util.module_from_spec(spec)
spec.loader.exec_module(train_v5)

from han2ids.model import GlyphIDS
from han2ids.tokenizer import SPECIALS

FORM = "鄕\U000E0102"


def test_new_tokens_start_from_their_unified_character():
    itos = SPECIALS + ["⿰", "鄉", "門"]
    model = GlyphIDS(len(itos), "vit_small_patch16_224")
    payload = {"itos": itos, "args": {"encoder": "vit_small_patch16_224"}}
    grown, vocabulary = train_v5.extend(model, payload, [FORM, "門"])
    assert vocabulary == itos + [FORM]
    weight = grown.state_dict()["tok.weight"]
    assert torch.equal(weight[-1], weight[itos.index("鄉")])
    assert grown.head.weight is grown.tok.weight


def test_score_counts_printed_and_unified_agreement():
    rows = [{"char": "䦳", "font": "ipamj", "ids": "⿵門鄉"}, {"char": "䦳", "font": "noto", "ids": "⿵門鄉"}]
    result = train_v5.score(rows, ["⿵門鄉", "⿵門鄉"], unseen={"門"})
    assert result["exact"] == 0.5
    assert result["unified"] == 1.0
    assert result["unseen_component_rows"] == 2


def test_composer_skips_held_out_readings():
    composer = train_v5.Composer(ROOT, ["日", "月"], set(), [], {"⿰日月", "⿰月日", "⿰日日", "⿰月月",
                                                              "⿱日月", "⿱月日", "⿱日日", "⿱月月"}, 0.0)
    composer.fonts, composer.covered = {"noto": [], "ipamj": [], "jigmo": []}, {name: ["日", "月"] for name in train_v5.FACES}
    composer.scarce = {name: [] for name in train_v5.FACES}
    import random
    assert composer.sample(random.Random(0)) is None
