import copy
import importlib.util
import json
import math
import sys
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest
import torch
from PIL import Image
from torch.utils.data import DataLoader


ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("accuracy_experiment", ROOT / "scripts/train_accuracy_experiment.py")
experiment = importlib.util.module_from_spec(spec)
spec.loader.exec_module(experiment)


def rows(chars):
    return [{"char": char, "font": font, "ids": "⿰木木", "split": "train"}
            for char in chars for font in ("a", "b")]


def test_sampling_keeps_all_fonts_for_each_character_and_is_stable():
    data = rows("一二三四五六七八九十")
    sample = experiment.sample_rows(data, 4, 19, "train")
    assert sample == experiment.sample_rows(data, 4, 19, "train")
    assert sample != experiment.sample_rows(data, 4, 20, "train")
    assert len(sample) == 8
    assert all(sum(row["char"] == char for _, row in sample) == 2 for char in {row["char"] for _, row in sample})
    assert [i for i, _ in sample] == sorted(i for i, _ in sample)
    with pytest.raises(ValueError, match="positive"):
        experiment.sample_rows(data, 0, 1, "train")


def test_sample_seed_is_independent_of_training_seed():
    base = ["--cache", "cache", "--init", "model.pt", "--out-dir", "out", "--font", "a=0=font.ttf",
            "--render", "legacy", "--epochs", "1", "--batch-size", "2", "--sample-seed", "9",
            "--gpu-fraction", "0.5", "--min-free-gib", "1"]
    one = experiment.parser().parse_args(base + ["--seed", "1"])
    two = experiment.parser().parse_args(base + ["--seed", "2"])
    data = rows("一二三四五六")
    assert one.seed != two.seed
    assert experiment.sample_rows(data, 3, one.sample_seed, "train") == experiment.sample_rows(data, 3, two.sample_seed, "train")


def test_evaluation_conditions_name_epoch_zero_without_model_inference(tmp_path, monkeypatch):
    calls = []

    def fake_evaluate(model, rows, images, vocab, renderer, condition, batch_size, output):
        calls.append((condition, output.name))
        output.write_text(condition)
        return {"overall": {"rows": 1}}

    monkeypatch.setattr(experiment, "evaluate", fake_evaluate)
    results = experiment.evaluate_conditions(None, [], None, None, None, 1, tmp_path, 0)
    assert calls == [("legacy", "val_epoch_0_legacy.jsonl"), ("clean", "val_epoch_0_clean.jsonl")]
    assert results["legacy"]["predictions_sha256"] == experiment.sha256_file(tmp_path / "val_epoch_0_legacy.jsonl")


def test_reads_only_train_and_val(tmp_path):
    for part, chars in (("train", "一二"), ("val", "三四")):
        data = [{**r, "split": part} for r in rows(chars)]
        (tmp_path / f"{part}.jsonl").write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in data))
        np.save(tmp_path / f"{part}.npy", np.zeros((len(data), 224, 224), dtype=np.uint8))
    train, _ = experiment.read_split(tmp_path, "train", 1, 5)
    val, _ = experiment.read_split(tmp_path, "val", 1, 5)
    assert len(train) == len(val) == 2
    assert {r["char"] for _, r in train}.isdisjoint({r["char"] for _, r in val})
    with pytest.raises(ValueError, match="only train and val"):
        experiment.read_split(tmp_path, "test", None, 5)


def test_read_rejects_mismatched_image_count(tmp_path):
    (tmp_path / "train.jsonl").write_text(json.dumps(rows("一")[0], ensure_ascii=False) + "\n")
    np.save(tmp_path / "train.npy", np.zeros((0, 224, 224), dtype=np.uint8))
    with pytest.raises(ValueError, match="shape"):
        experiment.read_split(tmp_path, "train", None, 1)


def test_output_directory_never_overwrites(tmp_path):
    target = tmp_path / "run"
    experiment.create_output(target)
    (target / "existing").write_text("keep")
    with pytest.raises(FileExistsError):
        experiment.create_output(target)
    assert (target / "existing").read_text() == "keep"


def test_validation_checks_overlap_missing_tokens_and_length(monkeypatch):
    monkeypatch.setattr(experiment, "gold", lambda char, font, fallback: fallback)
    vocab = experiment.Vocabulary(["<pad>", "<bos>", "<eos>", "<unk>", "⿰", "木"])
    train = [(0, rows("一")[0])]
    val = [(0, {**rows("二")[0], "split": "val"})]
    experiment.validate_rows(train, val, vocab, 5, {"a": []})
    with pytest.raises(ValueError, match="too long"):
        experiment.validate_rows(train, val, vocab, 4, {"a": []})
    with pytest.raises(ValueError, match="unknown"):
        experiment.validate_rows(train, [(0, {**val[0][1], "ids": "⿰木水"})], vocab, 5, {"a": []})
    with pytest.raises(ValueError, match="overlap"):
        experiment.validate_rows(train, train, vocab, 5, {"a": []})
    with pytest.raises(ValueError, match="missing font"):
        experiment.validate_rows(train, val, vocab, 5, {})


def test_dataset_seed_is_per_row_and_epoch(monkeypatch):
    import han2ids.augmentation as augmentation
    monkeypatch.setattr(experiment, "gold", lambda char, font, fallback: fallback)
    monkeypatch.setattr(augmentation, "augment", lambda image, rng: Image.new("L", (224, 224), rng.randrange(256)))
    vocab = experiment.Vocabulary(["<pad>", "<bos>", "<eos>", "<unk>", "⿰", "木"])
    dataset = experiment.Rows([(7, rows("一")[0])], np.zeros((8, 224, 224), dtype=np.uint8), vocab, None, "legacy", 5, True)
    first, tokens = dataset[0]
    second, _ = dataset[0]
    assert experiment.torch.equal(first, second)
    assert tokens.tolist() == [1, 4, 5, 5, 2]
    dataset.epoch = 1
    assert not experiment.torch.equal(first, dataset[0][0])


def test_render_condition_selects_cache_or_renderer_without_dropping_rows(monkeypatch):
    monkeypatch.setattr(experiment, "gold", lambda char, font, fallback: fallback)
    vocab = experiment.Vocabulary(["<pad>", "<bos>", "<eos>", "<unk>", "⿰", "木"])
    calls = []

    class Renderer:
        def render(self, char, family):
            calls.append((char, family))
            return Image.new("L", (224, 224), 255)

    data = list(enumerate(rows("一")))
    images = np.zeros((2, 224, 224), dtype=np.uint8)
    legacy = experiment.Rows(data, images, vocab, Renderer(), "legacy", 5)
    clean = experiment.Rows(data, images, vocab, Renderer(), "clean", 5)
    assert len(legacy) == len(clean) == 2
    assert legacy[0][0].min().item() == -1
    assert calls == []
    assert clean[0][0].min().item() == 1
    assert calls == [("一", "a")]
    assert experiment.torch.equal(legacy[0][1], clean[0][1])


def test_sampled_rows_pair_cache_pixels_with_labels(monkeypatch):
    monkeypatch.setattr(experiment, "gold", lambda char, font, fallback: fallback)
    vocab = experiment.Vocabulary(["<pad>", "<bos>", "<eos>", "<unk>", "木", "水", "火"])
    selected = [(1, {"char": "一", "font": "a", "ids": "木"}),
                (4, {"char": "二", "font": "b", "ids": "水"}),
                (7, {"char": "三", "font": "a", "ids": "火"})]
    images = np.stack([np.full((224, 224), i * 25, dtype=np.uint8) for i in range(8)])
    dataset = experiment.Rows(selected, images, vocab, None, "legacy", 0)
    for position, (index, row) in enumerate(selected):
        image, tokens = dataset[position]
        assert image.shape == (3, 224, 224)
        torch.testing.assert_close(image, torch.full_like(image, index * 25 / 127.5 - 1))
        assert tokens.tolist() == [experiment.BOS, vocab.stoi[row["ids"]], experiment.EOS]


def test_evaluate_pairs_sampled_rows_across_short_final_batch(tmp_path, monkeypatch):
    monkeypatch.setattr(experiment, "gold", lambda char, font, fallback: fallback)
    monkeypatch.setattr(torch.Tensor, "cuda", lambda self: self)
    vocab = experiment.Vocabulary(["<pad>", "<bos>", "<eos>", "<unk>", "木", "水", "火", "土", "金"])
    selected = [(index, {"char": char, "font": font, "ids": label})
                for index, char, font, label in zip((1, 3, 5, 7, 9), "一二三四五", "ababa", "木水火土金")]
    images = np.stack([np.full((224, 224), i * 20, dtype=np.uint8) for i in range(10)])
    token_by_pixel = {index * 20: vocab.stoi[row["ids"]] for index, row in selected}
    batches = []

    def generate(model, x, itos, max_len):
        assert x.device.type == "cpu"
        pixels = ((x[:, 0, 0, 0] + 1) * 127.5).round().int().tolist()
        batches.append(pixels)
        return torch.tensor([[experiment.BOS, token_by_pixel[pixel], experiment.EOS] for pixel in pixels]), None

    monkeypatch.setattr(experiment, "generate", generate)
    model = type("Model", (), {"max_len": 8})()
    output = tmp_path / "predictions.jsonl"
    metrics = experiment.evaluate(model, selected, images, vocab, None, "legacy", 2, output)
    records = [json.loads(line) for line in output.read_text(encoding="utf-8").splitlines()]
    assert batches == [[20, 60], [100, 140], [180]]
    assert records == [{"row_index": index, "char": row["char"], "font": row["font"],
                        "gold": row["ids"], "prediction": row["ids"],
                        "token_ids": [experiment.BOS, vocab.stoi[row["ids"]], experiment.EOS], "exact": True}
                       for index, row in selected]
    assert metrics["overall"]["rows"] == 5
    assert metrics["overall"]["exact_row_agreement"] == 1


def test_agreement_uses_equal_character_weight_and_font_breakdown():
    records = [{"char": "一", "font": "a", "exact": True},
               {"char": "一", "font": "b", "exact": False},
               {"char": "二", "font": "a", "exact": True}]
    result = experiment.agreement(records)
    assert result["overall"]["exact_row_agreement"] == pytest.approx(2 / 3)
    assert result["overall"]["exact_character_macro_agreement"] == .75
    assert result["per_font"]["a"]["exact_character_macro_agreement"] == 1
    assert result["per_font"]["b"]["exact_character_macro_agreement"] == 0


def test_font_specs_preserve_family_order(tmp_path):
    first, second = tmp_path / "one.ttf", tmp_path / "two.ttf"
    first.touch()
    second.touch()
    assert experiment.parse_fonts([f"jigmo=0={first}", f"jigmo=2={second}"]) == {"jigmo": [(first, 0), (second, 2)]}
    with pytest.raises(ValueError, match="invalid --font"):
        experiment.parse_fonts([f"jigmo=-1={first}"])


def cli_args():
    return ["--cache", "cache", "--init", "model.pt", "--out-dir", "out", "--font", "a=0=font.ttf",
            "--render", "legacy", "--epochs", "1", "--batch-size", "2", "--seed", "1", "--sample-seed", "9",
            "--gpu-fraction", "0.5", "--min-free-gib", "1"]


def test_accumulation_and_evaluation_cli():
    args = experiment.parser().parse_args(cli_args())
    assert args.accumulation_steps == 1
    assert args.eval_batch_size is None
    args = experiment.parser().parse_args(cli_args() + ["--accumulation-steps", "3", "--eval-batch-size", "7"])
    assert (args.batch_size, args.accumulation_steps, args.eval_batch_size) == (2, 3, 7)
    for option in ("--accumulation-steps", "--eval-batch-size"):
        for value in ("0", "-1", "x"):
            with pytest.raises(SystemExit):
                experiment.parser().parse_args(cli_args() + [option, value])


def test_learning_rate_cli_validation():
    args = experiment.parser().parse_args(cli_args())
    assert (args.encoder_lr, args.decoder_lr) == (5e-5, 2.5e-4)
    args = experiment.parser().parse_args(cli_args() + ["--encoder-lr", "1e-5", "--decoder-lr", "5e-5"])
    assert (args.encoder_lr, args.decoder_lr) == (1e-5, 5e-5)
    for option in ("--encoder-lr", "--decoder-lr"):
        for value in ("0", "-1", "nan", "inf", "x"):
            with pytest.raises(SystemExit):
                experiment.parser().parse_args(cli_args() + [option, value])


def test_learning_rates_configure_optimizer_groups():
    model = torch.nn.Module()
    model.encoder = torch.nn.Linear(2, 2)
    model.decoder = torch.nn.Linear(2, 2)
    optimizer = experiment.make_optimizer(model, 1e-5, 5e-5)
    assert [group["lr"] for group in optimizer.param_groups] == [1e-5, 5e-5]
    assert {id(p) for p in optimizer.param_groups[0]["params"]} == {id(p) for p in model.encoder.parameters()}
    assert {id(p) for p in optimizer.param_groups[1]["params"]} == {id(p) for p in model.decoder.parameters()}


def test_cuda_memory_cli_validation():
    args = experiment.parser().parse_args(cli_args())
    assert args.gpu_fraction == 0.5
    assert args.min_free_gib == 1
    for option in ("--gpu-fraction", "--min-free-gib"):
        base = cli_args()
        position = base.index(option)
        del base[position:position + 2]
        with pytest.raises(SystemExit):
            experiment.parser().parse_args(base)
        for value in ("0", "-1", "nan", "inf", "-inf", "x"):
            with pytest.raises(SystemExit):
                experiment.parser().parse_args(cli_args() + [option, value])
    with pytest.raises(SystemExit):
        experiment.parser().parse_args(cli_args() + ["--gpu-fraction", "1.01"])
    assert experiment.parser().parse_args(cli_args() + ["--gpu-fraction", "1"]).gpu_fraction == 1


def fake_main_inputs(monkeypatch):
    monkeypatch.setenv("CUBLAS_WORKSPACE_CONFIG", ":4096:8")
    monkeypatch.setattr(experiment, "parse_fonts", lambda specs: {})
    monkeypatch.setattr(experiment, "read_split", lambda cache, split, limit, seed:
                        ([(0, {"char": "一" if split == "train" else "二"})] * 4, None))
    monkeypatch.setattr(torch, "load", lambda *args, **kwargs: {"itos": [], "args": {}})
    monkeypatch.setattr(experiment, "Vocabulary", lambda itos: None)
    monkeypatch.setattr(experiment, "validate_rows", lambda *args: None)
    monkeypatch.setattr(torch.cuda, "is_available", lambda: True)


def test_insufficient_cuda_memory_refuses_before_output(tmp_path, monkeypatch):
    fake_main_inputs(monkeypatch)
    calls = []
    monkeypatch.setattr(torch.cuda, "mem_get_info", lambda: (1024 ** 3 - 1, 8 * 1024 ** 3))
    monkeypatch.setattr(torch.cuda, "set_per_process_memory_fraction", lambda fraction: calls.append(fraction))
    output = tmp_path / "run"
    with pytest.raises(RuntimeError, match="Insufficient free CUDA memory"):
        experiment.main(cli_args() + ["--out-dir", str(output)])
    assert calls == []
    assert not output.exists()


def test_cuda_memory_guard_sets_fraction_and_records_info(monkeypatch):
    calls = []
    monkeypatch.setattr(torch.cuda, "is_available", lambda: True)
    monkeypatch.setattr(torch.cuda, "mem_get_info", lambda: (2 * 1024 ** 3, 8 * 1024 ** 3))
    monkeypatch.setattr(torch.cuda, "set_per_process_memory_fraction", lambda fraction: calls.append(fraction))
    settings = experiment.guard_cuda_memory(0.75, 2)
    assert calls == [0.75]
    assert settings == {"requested_allocator_fraction": 0.75, "min_free_gib": 2,
                        "free_bytes": 2 * 1024 ** 3, "total_bytes": 8 * 1024 ** 3,
                        "allocator_fraction_note": "The allocator fraction excludes CUDA context memory."}


def test_successful_cuda_guard_precedes_output(tmp_path, monkeypatch):
    fake_main_inputs(monkeypatch)
    monkeypatch.setitem(sys.modules, "han2ids.training_render", SimpleNamespace(FontRenderer=lambda fonts: None))
    calls = []
    monkeypatch.setattr(torch.cuda, "mem_get_info", lambda: (2 * 1024 ** 3, 8 * 1024 ** 3))
    monkeypatch.setattr(torch.cuda, "set_per_process_memory_fraction", lambda fraction: calls.append(("fraction", fraction)))

    def stop_at_output(path):
        calls.append(("output", path))
        raise RuntimeError("output reached")

    monkeypatch.setattr(experiment, "create_output", stop_at_output)
    output = tmp_path / "run"
    with pytest.raises(RuntimeError, match="output reached"):
        experiment.main(cli_args() + ["--out-dir", str(output)])
    assert calls == [("fraction", 0.5), ("output", output)]
    assert not output.exists()


def test_safe_path_resolves_home_root_relative_and_outside(tmp_path, monkeypatch):
    home = tmp_path / "private-user"
    home.mkdir()
    monkeypatch.setattr(Path, "home", lambda: home)
    (tmp_path / "home-link").symlink_to(home, target_is_directory=True)
    assert experiment.safe_path(home) == "$HOME"
    assert experiment.safe_path(tmp_path / "home-link" / "dir" / ".." / "file") == "$HOME/file"
    assert experiment.safe_path(tmp_path / "private-user-other" / "file") == str(tmp_path / "private-user-other" / "file")
    monkeypatch.chdir(home)
    assert experiment.safe_path(Path("relative/file")) == "$HOME/relative/file"
    assert experiment.safe_path(Path("~/model.pt")) == "$HOME/~/model.pt"
    assert experiment.safe_path(Path("~nonexistent/model.pt")) == "$HOME/~nonexistent/model.pt"


@pytest.mark.parametrize("in_home", [True, False])
def test_settings_redact_home_paths_and_preserve_hashes(tmp_path, monkeypatch, in_home):
    home = tmp_path / "private-user"
    home.mkdir()
    monkeypatch.setattr(Path, "home", lambda: home)
    base = home if in_home else tmp_path / "outside"
    base.mkdir(exist_ok=True)
    cache = base / "cache"
    cache.mkdir()
    init = base / "init.pt"
    font = base / "font.ttf"
    for path in [init, font, *(cache / f"{part}.{ext}" for part in ("train", "val") for ext in ("jsonl", "npy"))]:
        path.write_bytes(str(path.name).encode())
    parse_fonts = experiment.parse_fonts
    fake_main_inputs(monkeypatch)
    monkeypatch.setattr(experiment, "parse_fonts", parse_fonts)
    monkeypatch.setitem(sys.modules, "han2ids.training_render", SimpleNamespace(FontRenderer=lambda fonts: None))
    monkeypatch.setattr(experiment, "guard_cuda_memory", lambda *args: {})
    monkeypatch.setattr(torch.cuda, "get_device_name", lambda: "fake GPU")
    monkeypatch.setattr(torch.backends.cudnn, "version", lambda: 12345)
    monkeypatch.setattr(torch.cuda, "manual_seed_all", lambda seed: None)
    monkeypatch.setattr(torch, "manual_seed", lambda seed: None)
    monkeypatch.setattr(torch, "use_deterministic_algorithms", lambda enabled: None)
    monkeypatch.setattr(experiment.importlib.metadata, "version", lambda package: "fake-version")
    captured = {}

    def capture_settings(path, content, **kwargs):
        assert path.name == "settings.json"
        captured.update(json.loads(content))
        raise RuntimeError("settings captured")

    monkeypatch.setattr(Path, "write_text", capture_settings)
    args = cli_args()
    font_option = args.index("--font")
    args[font_option + 1] = f"a=2={font}"
    args += ["--cache", str(cache), "--init", str(init), "--out-dir", str(tmp_path / "run")]
    with pytest.raises(RuntimeError, match="settings captured"):
        experiment.main(args)
    prefix = "$HOME" if in_home else str(base)
    assert captured["cache"] == f"{prefix}/cache"
    assert captured["init"] == f"{prefix}/init.pt"
    assert captured["fonts"]["a"] == [{"path": f"{prefix}/font.ttf", "index": 2,
                                       "sha256": experiment.sha256_file(font)}]
    expected_inputs = {f"{prefix}/init.pt": experiment.sha256_file(init)}
    expected_inputs.update({f"{prefix}/cache/{part}.{ext}": experiment.sha256_file(cache / f"{part}.{ext}")
                            for part in ("train", "val") for ext in ("jsonl", "npy")})
    for name in ("IDS.TXT", "label-overrides.tsv", "font-label-overrides.tsv"):
        path = experiment.ROOT / "data" / name
        expected_inputs[experiment.safe_path(path)] = experiment.sha256_file(path)
    assert captured["inputs_sha256"] == expected_inputs
    assert str(home) not in json.dumps(captured)
    assert "private-user" not in json.dumps(captured)


def test_cuda_memory_is_in_settings(tmp_path, monkeypatch):
    fake_main_inputs(monkeypatch)
    monkeypatch.setitem(sys.modules, "han2ids.training_render", SimpleNamespace(FontRenderer=lambda fonts: None))
    monkeypatch.setattr(torch.cuda, "mem_get_info", lambda: (2 * 1024 ** 3, 8 * 1024 ** 3))
    monkeypatch.setattr(torch.cuda, "set_per_process_memory_fraction", lambda fraction: None)
    monkeypatch.setattr(torch.cuda, "get_device_name", lambda: "fake GPU")
    monkeypatch.setattr(torch.backends.cudnn, "version", lambda: 12345)
    monkeypatch.setattr(torch.cuda, "manual_seed_all", lambda seed: None)
    monkeypatch.setattr(torch, "manual_seed", lambda seed: None)
    monkeypatch.setattr(torch, "use_deterministic_algorithms", lambda enabled: None)
    monkeypatch.setattr(experiment, "sha256_file", lambda path: "fake-hash")
    monkeypatch.setattr(experiment.importlib.metadata, "version", lambda package: "fake-version")
    captured = {}

    def capture_settings(path, content, **kwargs):
        assert path.name == "settings.json"
        captured.update(json.loads(content))
        raise RuntimeError("settings captured")

    monkeypatch.setattr(Path, "write_text", capture_settings)
    with pytest.raises(RuntimeError, match="settings captured"):
        experiment.main(cli_args() + ["--out-dir", str(tmp_path / "run"), "--encoder-lr", "1e-5", "--decoder-lr", "5e-5"])
    assert captured["optimizer"]["encoder_lr"] == 1e-5
    assert captured["optimizer"]["other_lr"] == 5e-5
    assert captured["cuda_memory"] == {
        "requested_allocator_fraction": 0.5, "min_free_gib": 1,
        "free_bytes": 2 * 1024 ** 3, "total_bytes": 8 * 1024 ** 3,
        "allocator_fraction_note": "The allocator fraction excludes CUDA context memory."}


class ToyModel(torch.nn.Module):
    def __init__(self):
        super().__init__()
        self.embedding = torch.nn.Embedding(8, 5)
        self.image = torch.nn.Linear(2, 5)
        self.output = torch.nn.Linear(5, 8)

    def forward(self, x, y):
        return self.output(torch.tanh(self.embedding(y) + self.image(x).unsqueeze(1)))


def test_accumulation_matches_physical_batches_with_partial_group(monkeypatch):
    torch.manual_seed(47)
    model = ToyModel()
    physical = copy.deepcopy(model)
    # Eleven rows give groups of 4, 4 and 3, with different target-token counts.
    data = [(torch.tensor([i / 10, (i % 3) / 3]),
             torch.tensor([1] + [3 + (i + j) % 5 for j in range(i % 4 + 1)] + [2]))
            for i in range(11)]
    micro_loader = DataLoader(data, batch_size=2, collate_fn=experiment.collate)
    physical_loader = DataLoader(data, batch_size=4, collate_fn=experiment.collate)
    epochs = 2
    total_steps = experiment.update_count(len(micro_loader), 2, epochs)
    assert total_steps == 6
    optimizers = [torch.optim.AdamW(m.parameters(), lr=0.01, weight_decay=0.05) for m in (model, physical)]
    schedulers = [experiment.make_scheduler(opt, total_steps) for opt in optimizers]
    histories = [[], []]
    learning_rates = [[], []]
    unclipped = []
    clip = torch.nn.utils.clip_grad_norm_

    def capture_clip(parameters, max_norm, **kwargs):
        parameters = list(parameters)
        unclipped.append([p.grad.detach().clone() for p in parameters])
        return clip(parameters, max_norm, **kwargs)

    monkeypatch.setattr(torch.nn.utils, "clip_grad_norm_", capture_clip)

    def physical_epoch():
        physical.train()
        loss_sum = token_count = row_count = updates = 0
        for x, y in physical_loader:
            optimizers[1].zero_grad(set_to_none=True)
            logits = physical(x, y[:, :-1])
            loss = torch.nn.functional.cross_entropy(logits.reshape(-1, 8), y[:, 1:].reshape(-1),
                                                     ignore_index=experiment.PAD, label_smoothing=0.17)
            count = y[:, 1:].ne(experiment.PAD).sum().item()
            loss_sum += loss.item() * count
            token_count += count
            row_count += len(x)
            loss.backward()
            torch.nn.utils.clip_grad_norm_(physical.parameters(), 0.2)
            optimizers[1].step()
            schedulers[1].step()
            updates += 1
        return {"train_rows": row_count, "train_tokens": token_count, "train_updates": updates,
                "train_loss_token_weighted": loss_sum / token_count}
    for index, optimizer in enumerate(optimizers):
        def capture_before(opt, args, kwargs, index=index):
            histories[index].append({"grads": [p.grad.detach().clone() for group in opt.param_groups for p in group["params"]]})
            learning_rates[index].append(opt.param_groups[0]["lr"])
        def capture_after(opt, args, kwargs, index=index):
            histories[index][-1]["weights"] = [p.detach().clone() for group in opt.param_groups for p in group["params"]]
        optimizer.register_step_pre_hook(capture_before)
        optimizer.register_step_post_hook(capture_after)
    assert all(opt.param_groups[0]["lr"] == 0 for opt in optimizers)
    for _ in range(epochs):
        accumulated = experiment.train_epoch(model, micro_loader, optimizers[0], schedulers[0], 2, "cpu",
                                             label_smoothing=0.17, gradient_clip=0.2)
        baseline = physical_epoch()
        assert accumulated["train_rows"] == baseline["train_rows"] == 11
        assert accumulated["train_tokens"] == baseline["train_tokens"] == sum(len(y) - 1 for _, y in data)
        assert accumulated["train_updates"] == baseline["train_updates"] == 3
        assert accumulated["train_loss_token_weighted"] == pytest.approx(baseline["train_loss_token_weighted"], abs=1e-6)
    assert [s.last_epoch for s in schedulers] == [total_steps, total_steps]
    assert len(histories[0]) == len(histories[1]) == total_steps
    # Each epoch clips three accumulated groups followed by three physical batches.
    assert len(unclipped) == total_steps * 2
    for epoch in range(epochs):
        for actual_group, expected_group in zip(unclipped[epoch * 6:epoch * 6 + 3], unclipped[epoch * 6 + 3:epoch * 6 + 6]):
            for actual, expected in zip(actual_group, expected_group):
                torch.testing.assert_close(actual, expected, rtol=2e-5, atol=2e-7)
    assert learning_rates[0] == pytest.approx(learning_rates[1])
    assert learning_rates[0][0] == 0 and learning_rates[0][1] > 0
    for step, lr in enumerate(learning_rates[0]):
        expected = 0.01 * min(1, step / max(1, total_steps // 20)) * 0.5 * (1 + math.cos(math.pi * step / total_steps))
        assert lr == pytest.approx(expected)
    for accumulated_step, physical_step in zip(*histories):
        for key in ("grads", "weights"):
            for actual, expected in zip(accumulated_step[key], physical_step[key]):
                torch.testing.assert_close(actual, expected, rtol=2e-5, atol=2e-7)
    assert any(not torch.equal(a, b) for a, b in zip(histories[0][0]["weights"], histories[0][1]["weights"]))


def test_attention_decoder_accumulation_matches_physical_batch(monkeypatch):
    import han2ids.model as model_module

    class TinyEncoder(torch.nn.Module):
        num_features = 8

        def __init__(self):
            super().__init__()
            self.projection = torch.nn.Linear(2, 8)

        def forward_features(self, images):
            return self.projection(images).unsqueeze(1)

    monkeypatch.setattr(model_module.timm, "create_model", lambda *args, **kwargs: TinyEncoder())
    torch.manual_seed(73)
    accumulated = model_module.GlyphIDS(8, "unused", d_model=8, layers=1, heads=2, max_len=8, dropout=0)
    physical = copy.deepcopy(accumulated)
    data = [(torch.tensor([0.1, 0.2]), torch.tensor([1, 3, 2])),
            (torch.tensor([0.3, 0.4]), torch.tensor([1, 4, 2])),
            (torch.tensor([0.5, 0.6]), torch.tensor([1, 5, 6, 7, 2]))]
    micro_loader = DataLoader(data, batch_size=2, collate_fn=experiment.collate)
    full_loader = DataLoader(data, batch_size=3, collate_fn=experiment.collate)
    assert [y.shape[1] for _, y in micro_loader] == [3, 5]
    captured = []
    clip = torch.nn.utils.clip_grad_norm_

    def capture_clip(parameters, max_norm, **kwargs):
        parameters = list(parameters)
        captured.append([p.grad.detach().clone() for p in parameters])
        return clip(parameters, max_norm, **kwargs)

    monkeypatch.setattr(torch.nn.utils, "clip_grad_norm_", capture_clip)
    results = []
    for model, loader, steps in ((accumulated, micro_loader, 2), (physical, full_loader, 1)):
        optimizer = torch.optim.SGD(model.parameters(), lr=0.01)
        scheduler = torch.optim.lr_scheduler.LambdaLR(optimizer, lambda _: 1)
        results.append(experiment.train_epoch(model, loader, optimizer, scheduler, steps, "cpu",
                                              label_smoothing=0.1, gradient_clip=100))
    assert results[0]["train_tokens"] == results[1]["train_tokens"] == 8
    assert results[0]["train_updates"] == results[1]["train_updates"] == 1
    assert results[0]["train_loss_token_weighted"] == pytest.approx(results[1]["train_loss_token_weighted"], abs=1e-6)
    assert len(captured) == 2
    for actual, expected in zip(*captured):
        torch.testing.assert_close(actual, expected, rtol=2e-5, atol=2e-7)
    for actual, expected in zip(accumulated.parameters(), physical.parameters()):
        torch.testing.assert_close(actual, expected, rtol=2e-5, atol=2e-7)


def test_single_update_is_rejected_before_output_or_gpu(tmp_path, monkeypatch):
    monkeypatch.setenv("CUBLAS_WORKSPACE_CONFIG", ":4096:8")
    monkeypatch.setattr(experiment, "parse_fonts", lambda specs: {})
    splits = []

    def read_split(cache, split, limit, seed):
        splits.append(split)
        if split == "val":
            raise RuntimeError("validation split reached")
        return [None] * 3, None

    monkeypatch.setattr(experiment, "read_split", read_split)
    monkeypatch.setattr(torch.cuda, "is_available", lambda: pytest.fail("GPU check reached"))
    output = tmp_path / "run"
    args = cli_args() + ["--out-dir", str(output), "--accumulation-steps", "2"]
    with pytest.raises(ValueError, match="at least two optimizer updates.*initial learning rate is zero"):
        experiment.main(args)
    assert splits == ["train"]
    assert not output.exists()
    # One update per epoch is valid when at least two epochs are planned.
    with pytest.raises(RuntimeError, match="validation split reached"):
        experiment.main(args + ["--epochs", "2"])
    assert not output.exists()


def test_nonfinite_gradients_fail_before_optimizer_step():
    model = ToyModel()
    optimizer = torch.optim.AdamW(model.parameters(), lr=0.01)
    scheduler = experiment.make_scheduler(optimizer, 2)
    before = [p.detach().clone() for p in model.parameters()]
    batch = [(torch.tensor([float("nan"), 0.0]), torch.tensor([1, 3, 2]))]
    loader = DataLoader(batch, batch_size=1, collate_fn=experiment.collate)
    with pytest.raises(RuntimeError, match="non-finite"):
        experiment.train_epoch(model, loader, optimizer, scheduler, 1, "cpu")
    assert scheduler.last_epoch == 0
    assert not optimizer.state
    for actual, expected in zip(model.parameters(), before):
        torch.testing.assert_close(actual, expected)


def test_scheduler_update_count_rounds_each_epoch_and_warmup():
    assert experiment.update_count(5, 2, 3) == 9
    assert experiment.update_count(2, 4, 3) == 3
    model = torch.nn.Linear(1, 1)
    optimizer = torch.optim.AdamW(model.parameters(), lr=1.0)
    scheduler = experiment.make_scheduler(optimizer, 40)
    assert optimizer.param_groups[0]["lr"] == 0
    for step in range(1, 41):
        optimizer.step()
        scheduler.step()
        assert optimizer.param_groups[0]["lr"] == pytest.approx(min(1, step / 2) * 0.5 * (1 + math.cos(math.pi * step / 40)))
    assert scheduler.last_epoch == 40
