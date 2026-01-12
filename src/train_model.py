"""
Train YOLO Model for Speed Sign Detection
==========================================
This script trains a YOLOv8 model and saves it to the weights/ folder
where your project expects it.

BEFORE RUNNING:
1. Download your dataset from Roboflow in "YOLOv8" format
2. Extract the zip file
3. Update DATA_PATH below to point to your data.yaml

AFTER RUNNING:
- Your trained model will be at: weights/best.pt
- Your project (main.py) will automatically use it
"""

import os
import shutil
from pathlib import Path

import torch

# Check if MPS (M1 GPU) is available
if torch.backends.mps.is_available():
    DEVICE = "mps"  # Use M1 GPU!
    print("✅ Apple M1 GPU (MPS) detected! Using GPU acceleration.")
elif torch.cuda.is_available():
    DEVICE = 0  # Use NVIDIA GPU
    print("✅ NVIDIA GPU detected!")
else:
    DEVICE = "cpu"
    print("⚠️  No GPU detected, using CPU (slow)")



DATA_PATH = "/Users/alexanderabdu/Documents/Honours-Stage-Project-/dataset/data.yaml"

# Training settings
EPOCHS = 100  # More epochs = better accuracy, but takes longer
MODEL_SIZE = "yolov8n.pt"  # n=nano (fast), s=small, m=medium (accurate)
BATCH_SIZE = 16  # Reduce to 8 or 4 if you get memory errors
IMAGE_SIZE = 640  # Standard size, don't change unless needed



# ============================================================
# TRAINING CODE - DON'T EDIT
# ============================================================

def train():
    """Train the YOLO model."""
    from ultralytics import YOLO


    print("YOLO SPEED SIGN TRAINING")

    print(f"\nSettings:")
    print(f"  Dataset:     {DATA_PATH}")
    print(f"  Model:       {MODEL_SIZE}")
    print(f"  Epochs:      {EPOCHS}")
    print(f"  Batch size:  {BATCH_SIZE}")
    print(f"  Image size:  {IMAGE_SIZE}")
    print("\nThis may take a while... (30 mins - 2 hours depending on hardware)")
    print("=" * 60 + "\n")

    # Load pretrained model
    model = YOLO(MODEL_SIZE)

    # Train
    results = model.train(
        data=DATA_PATH,
        epochs=EPOCHS,
        device=DEVICE,
        batch=BATCH_SIZE,
        imgsz=IMAGE_SIZE,
        patience=50,  # Stop early if no improvement for 50 epochs

        # Augmentation (important for traffic signs!)
        flipud=0.0,  # DON'T flip upside down
        fliplr=0.0,  # DON'T flip left-right (numbers would reverse)
        degrees=10.0,  # Slight rotation
        translate=0.1,  # Slight position shift
        scale=0.5,  # Zoom in/out
        hsv_h=0.015,  # Color variation
        hsv_s=0.7,  # Saturation variation
        hsv_v=0.4,  # Brightness variation

        # Output location
        project="runs/train",
        name="speed_signs",

        # Save settings
        save=True,
        plots=True,
        verbose=True
    )

    return results


def copy_model_to_weights():
    """Copy the trained model to the weights/ folder."""

    # Source: where YOLO saves the model
    source = Path("runs/best.pt")

    # Destination: where your project expects it
    dest_folder = Path("runs/weights")
    dest = dest_folder / "best.pt"

    # Create weights folder if it doesn't exist
    dest_folder.mkdir(exist_ok=True)

    if source.exists():
        shutil.copy(source, dest)
        print(f"\n✅ Model copied to: {dest}")
        return True
    else:
        print(f"\n❌ Could not find trained model at: {source}")
        return False


def show_results():


    print("TRAINING COMPLETE!")

    print(f"""
Your trained model is ready!

Files created:
  📁 weights/best.pt          <- Your project uses this
  📁 runs/train/speed_signs/  <- Training logs and graphs

To run your project:
  python main.py --show --mock_gps

To see training graphs:
  Open: runs/train/speed_signs/results.png
""")
    print("=" * 60)


# ============================================================
# MAIN
# ============================================================

if __name__ == "__main__":
    # Step 1: Validate settings


    # Step 2: Train
    results = train()

    # Step 3: Copy model to weights folder
    copy_model_to_weights()

    # Step 4: Show results
    show_results()