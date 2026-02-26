"""
Generate Printable Speed Signs for Testing
==========================================
Creates PDF with UK-style speed limit signs for printing.
"""

import matplotlib.pyplot as plt
import matplotlib.patches as patches
from matplotlib.backends.backend_pdf import PdfPages
import numpy as np

def create_speed_sign(ax, speed_value, size=1.0):
    """
    Create a UK-style speed limit sign.
    White circle with red border and black number.
    """
    # Clear axis
    ax.clear()
    ax.set_xlim(-1.2, 1.2)
    ax.set_ylim(-1.2, 1.2)
    ax.set_aspect('equal')
    ax.axis('off')
    
    # Red outer circle (border)
    outer_circle = patches.Circle((0, 0), 1.0 * size, 
                                   facecolor='red', edgecolor='black', linewidth=2)
    ax.add_patch(outer_circle)
    
    # White inner circle
    inner_circle = patches.Circle((0, 0), 0.85 * size,
                                   facecolor='white', edgecolor='white')
    ax.add_patch(inner_circle)
    
    # Speed number
    fontsize = 72 * size if speed_value < 100 else 60 * size
    ax.text(0, 0, str(speed_value), 
            fontsize=fontsize, fontweight='bold',
            ha='center', va='center', color='black',
            fontfamily='Arial')


def create_speed_signs_pdf(filename='printable_speed_signs.pdf'):
    """Create a multi-page PDF with speed signs for printing."""
    
    # UK speed limits to generate
    speeds = [20, 30, 40, 50, 60, 70]
    
    with PdfPages(filename) as pdf:
        # Title page
        fig, ax = plt.subplots(figsize=(8.5, 11))
        ax.axis('off')
        ax.text(0.5, 0.7, 'SPEED SIGN DETECTION', fontsize=28, 
                ha='center', va='center', fontweight='bold')
        ax.text(0.5, 0.6, 'Printable Test Signs', fontsize=20,
                ha='center', va='center')
        ax.text(0.5, 0.45, 'Project: BA-25-1057', fontsize=14,
                ha='center', va='center')
        ax.text(0.5, 0.4, 'Student: Ojonibe Alexander Abdu', fontsize=14,
                ha='center', va='center')
        ax.text(0.5, 0.35, 'University of Hull', fontsize=14,
                ha='center', va='center')
        ax.text(0.5, 0.2, 'Print on A4 paper, cut out signs, and use for testing.',
                fontsize=12, ha='center', va='center', style='italic')
        pdf.savefig(fig, bbox_inches='tight')
        plt.close()
        
        # Individual large signs (one per page)
        for speed in speeds:
            fig, ax = plt.subplots(figsize=(8.5, 11))
            create_speed_sign(ax, speed, size=1.0)
            ax.set_title(f'{speed} mph', fontsize=16, pad=20)
            pdf.savefig(fig, bbox_inches='tight')
            plt.close()
        
        # Page with multiple smaller signs
        fig, axes = plt.subplots(2, 3, figsize=(8.5, 11))
        fig.suptitle('Speed Limit Signs - Small Version (for distance testing)', 
                     fontsize=14, fontweight='bold')
        
        for ax, speed in zip(axes.flatten(), speeds):
            create_speed_sign(ax, speed, size=0.8)
            ax.set_title(f'{speed} mph', fontsize=10)
        
        plt.tight_layout()
        pdf.savefig(fig, bbox_inches='tight')
        plt.close()
        
        # Instructions page
        fig, ax = plt.subplots(figsize=(8.5, 11))
        ax.axis('off')
        
        instructions = """
TESTING INSTRUCTIONS
====================

1. PRINTING
   - Print this PDF on white A4 paper
   - Use color printing for best results
   - Glossy paper may cause glare issues

2. CUTTING
   - Cut out individual signs
   - Leave small white border around red circle

3. MOUNTING
   - Attach to cardboard for rigidity
   - Mount on stands at various heights
   - Typical sign height: 1.5-2m from ground

4. TESTING DISTANCES
   - Start at 1 metre, move back gradually
   - Test at: 1m, 2m, 3m, 5m, 10m
   - Note detection distance for each sign

5. LIGHTING CONDITIONS
   - Test in various lighting:
     * Bright daylight
     * Indoor fluorescent
     * Low light
     * Backlit (window behind sign)

6. ANGLES
   - Test at various angles:
     * Head-on (0°)
     * 15° offset
     * 30° offset
     * 45° offset

7. RECORDING RESULTS
   - Note which signs are detected
   - Record confidence scores
   - Document any false positives/negatives
"""
        
        ax.text(0.1, 0.95, instructions, fontsize=11,
                va='top', ha='left', fontfamily='monospace',
                transform=ax.transAxes)
        
        pdf.savefig(fig, bbox_inches='tight')
        plt.close()
    
    print(f"Created: {filename}")
    print(f"Contains {len(speeds)} individual signs + overview page + instructions")


if __name__ == "__main__":
    create_speed_signs_pdf('/home/claude/hybrid_system/printable_speed_signs.pdf')
    print("\nPrint this PDF and use the signs for testing your detection system!")
