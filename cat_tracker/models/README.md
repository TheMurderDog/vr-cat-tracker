# Models

**Start with stock YOLO11s** (COCO-trained, which includes cats of every kind as class 15). It's the default in
`config.yaml`, and `train.bat` trains from it. In the training environment (`train.bat` creates it on its first run,
or any Python with `pip install ultralytics`), from this folder:

```
yolo export model=yolo11s.pt format=onnx imgsz=960 opset=17 dynamic=True simplify=True
```

That downloads `yolo11s.pt` and writes `yolo11s.onnx`. Keep both here.

The stock model knows what cats look like in general, but not from a ceiling camera or curled up asleep, so it
will miss your cat a lot at first. **Train it on yours for good results:** see [TRAINING.md](../TRAINING.md).

**Your own model.** `train.bat` writes `cat_finetuned.onnx` and `cat_finetuned_half.onnx` here. Point `config.yaml`
at the half one with `cat_class: 0`. Each training run overwrites them, so copy a good one somewhere safe before
training again.

YOLO11 and Ultralytics are AGPL-3.0, which is why this project is too.
