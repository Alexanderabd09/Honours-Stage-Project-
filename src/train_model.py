"""

Modes:
  - DEBUG:  5 epochs, 10% data    → ~5-10 minutes
  - QUICK:  20 epochs, 50% data   → ~1-2 hours
  - FULL:   100 epochs, 100% data → ~18-20 hours
"""

import os
import shutil
import torch
from pathlib import Path



DATA_PATH = "/Users/alexanderabdu/Documents/Honours-Stage-Project-/dataset/data.yaml"



MODE = "DEBUG"  # Options: "DEBUG", "QUICK", "FULL"

# Mode configurations
MODES = {
    "DEBUG": {
        "epochs": 5,
        "fraction": 0.1,      # Use only 10% of data
        "batch_size": 8,
        "imgsz": 320,         # Smaller images = faster
        "patience": 3,
        "description": "Quick test (~5-10 mins)"
    },
    "QUICK": {
        "epochs": 20,
        "fraction": 0.5,      # Use 50% of data
        "batch_size": 16,
        "imgsz": 480,
        "patience": 10,
        "description": "Medium training (~1-2 hours)"
    },
    "FULL": {
        "epochs": 100,
        "fraction": 1.0,      # Use all data
        "batch_size": 16,
        "imgsz": 640,
        "patience": 50,
        "description": "Full training (~18-20 hours)"
    }
}

MODEL_SIZE = "yolov8n.pt"  # nano = fastest



if torch.backends.mps.is_available():
    DEVICE = "mps"
    device_name = "Apple M1 GPU"
elif torch.cuda.is_available():
    DEVICE = 0
    device_name = "NVIDIA GPU"
else:
    DEVICE = "cpu"
    device_name = "CPU (slow!)"


def main():
    # Get mode settings
    if MODE not in MODES:
        print(f" Invalid mode: {MODE}")
        print(f" Choose from: {list(MODES.keys())}")
        return

    settings = MODES[MODE]

    # Validate data path
    if not os.path.exists(DATA_PATH):
        print(f"\n File not found: {DATA_PATH}\n")
        return

    from ultralytics import YOLO

    # Print configuration

    print("YOLO SPEED SIGN TRAINING")

    print(f"""
    Mode:        {MODE} - {settings['description']}
    
    Settings:
      Dataset:   {DATA_PATH}
      Model:     {MODEL_SIZE}
      Device:    {DEVICE} ({device_name})
      
    Training:
      Epochs:    {settings['epochs']}
      Data:      {int(settings['fraction'] * 100)}% of dataset
      Batch:     {settings['batch_size']}
      Image sz:  {settings['imgsz']}
      Patience:  {settings['patience']}
    """)



    # Load model
    model = YOLO(MODEL_SIZE)

    # Train
    results = model.train(
        data=DATA_PATH,
        epochs=settings['epochs'],
        batch=settings['batch_size'],
        imgsz=settings['imgsz'],
        patience=settings['patience'],
        fraction=settings['fraction'],  # KEY: Use subset of data!
        device=DEVICE,

        # Augmentation (good for traffic signs)
        flipud=0.0,         # Don't flip upside down
        fliplr=0.0,         # Don't flip horizontally
        degrees=10.0,
        translate=0.1,
        scale=0.5,
        hsv_h=0.015,
        hsv_s=0.7,
        hsv_v=0.4,

        # Output
        project="runs/train",
        name=f"speed_signs_{MODE.lower()}",

        # Saving
        save=True,
        plots=True,
        verbose=True,

        # Speed optimizations for debug
        workers=0 if MODE == "DEBUG" else 4,
        cache=True if MODE == "DEBUG" else False,  # Cache images in RAM for debug
    )

    # Copy model to weights folder
    copy_best_model(MODE)

    # Print results
    print_results(MODE, results)

    return results


def copy_best_model(mode):
    """Copy the best model to the weights folder."""
    train_dir = Path("runs/train")

    if not train_dir.exists():
        return

    # Find the latest training run for this mode
    pattern = f"speed_signs_{mode.lower()}"
    runs = sorted([d for d in train_dir.iterdir()
                   if d.is_dir() and d.name.startswith(pattern)])

    if not runs:
        return

    source = runs[-1] / "weights" / "best.pt"

    if mode == "DEBUG":
        dest = Path("weights/debug_model.pt")
    else:
        dest = Path("weights/best.pt")

    Path("weights").mkdir(exist_ok=True)

    if source.exists():
        shutil.copy(source, dest)
        print(f"\n✅ Model saved to: {dest}")







def test_model(model_path="weights/best.pt", image_path=None):
    """
    Quick test of a trained model.

    Usage:
        from train_debug import test_model
        test_model("weights/debug_model.pt", "test_image.jpg")
    """
    from ultralytics import YOLO
    import cv2

    if not os.path.exists(model_path):
        print(f"Model not found: {model_path}")
        return

    model = YOLO(model_path)

    if image_path and os.path.exists(image_path):
        # Test on specific image
        results = model.predict(image_path, save=True, conf=0.5)
        print(f"Results saved to: runs/detect/predict/")
    else:
        # Test on webcam
        print("Testing on webcam... Press 'q' to quit")
        cap = cv2.VideoCapture(0)

        while True:
            ret, frame = cap.read()
            if not ret:
                break

            results = model.predict(frame, conf=0.5, verbose=False)
            annotated = results[0].plot()

            cv2.imshow("Test", annotated)
            if cv2.waitKey(1) & 0xFF == ord('q'):
                break

        cap.release()
        cv2.destroyAllWindows()




if __name__ == "__main__":
    main()