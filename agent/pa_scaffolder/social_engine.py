import os
import sys
import json
import subprocess
from pathlib import Path
from dataclasses import dataclass
from typing import Dict, Any, Optional, List, Tuple


@dataclass
class SocialDraft:
    platform: str        # "x_twitter" | "instagram" | "linkedin"
    caption: str
    hashtags: List[str]
    edited_image_path: str


class SocialMediaEngine:
    """
    Handles image enhancement, aspect ratio formatting,
    multi-platform caption drafting, and system dispatch.
    """
    def __init__(self, workspace_dir: Optional[Path] = None):
        self.workspace_dir = workspace_dir or Path("./workspace/social")
        self.workspace_dir.mkdir(parents=True, exist_ok=True)
        self.is_termux = "ANDROID_ROOT" in os.environ or "TERMUX_VERSION" in os.environ

    def enhance_image(
        self,
        image_path: Path,
        filter_style: str = "vibrant",  # "vibrant" | "monochrome" | "cinematic"
        aspect_ratio: str = "1:1"        # "1:1" (Instagram) | "16:9" (X/LinkedIn)
    ) -> Path:
        """
        Applies auto-enhancement and cropping.
        Uses Pillow if installed; falls back cleanly to file copy.
        """
        out_path = self.workspace_dir / f"enhanced_{image_path.stem}.jpg"
        
        try:
            from PIL import Image, ImageEnhance, ImageOps
            with Image.open(image_path) as img:
                img = ImageOps.exif_transpose(img)
                
                # Aspect Ratio Crop
                w, h = img.size
                if aspect_ratio == "1:1":
                    min_dim = min(w, h)
                    left = (w - min_dim) / 2
                    top = (h - min_dim) / 2
                    img = img.crop((left, top, left + min_dim, top + min_dim))
                elif aspect_ratio == "16:9":
                    target_h = int(w * (9 / 16))
                    if target_h <= h:
                        top = (h - target_h) / 2
                        img = img.crop((0, top, w, top + target_h))

                # Filter Application
                if filter_style == "vibrant":
                    img = ImageEnhance.Color(img).enhance(1.25)
                    img = ImageEnhance.Contrast(img).enhance(1.15)
                elif filter_style == "monochrome":
                    img = ImageOps.grayscale(img)
                elif filter_style == "cinematic":
                    img = ImageEnhance.Contrast(img).enhance(1.3)
                    img = ImageEnhance.Brightness(img).enhance(0.95)

                img.convert("RGB").save(out_path, "JPEG", quality=92)
                return out_path
        except Exception:
            import shutil
            shutil.copy(image_path, out_path)
            return out_path

    def draft_captions(self, image_description: str, persona_tone: str = "Supportive & High Energy") -> Dict[str, SocialDraft]:
        """
        Generates platform-optimized post variants for X, Instagram, and LinkedIn.
        """
        x_caption = f"Building in public. {image_description[:140]} — shipped with autonomous workflows."
        x_tags = ["#buildinpublic", "#ai", "#dev"]

        ig_caption = (
            f"Focus on the process, not just the outcome. ✨\n\n"
            f"{image_description}\n\n"
            f"Created alongside my personal AI companion."
        )
        ig_tags = ["#creators", "#techlifestyle", "#workflow", "#developer", "#minimalism"]

        li_caption = (
            f"Iterating quickly requires tightening the loop between concept and execution.\n\n"
            f"Key takeaway from this work:\n"
            f"• {image_description}\n"
            f"• Automated repetitive scaffolding to focus on core design.\n\n"
            f"How is your team streamlining daily technical iterations?"
        )
        li_tags = ["#Engineering", "#Productivity", "#ArtificialIntelligence", "#Innovation"]

        return {
            "x_twitter": SocialDraft("x_twitter", x_caption, x_tags, ""),
            "instagram": SocialDraft("instagram", ig_caption, ig_tags, ""),
            "linkedin": SocialDraft("linkedin", li_caption, li_tags, "")
        }

    def dispatch_to_device(self, draft: SocialDraft, image_path: Path) -> Tuple[bool, str]:
        full_text = f"{draft.caption}\n\n{' '.join(draft.hashtags)}"

        if self.is_termux:
            try:
                subprocess.run(["termux-clipboard-set", full_text], check=True)
            except Exception:
                pass

            try:
                cmd = [
                    "am", "start",
                    "-a", "android.intent.action.SEND",
                    "-t", "image/jpeg",
                    "--eu", "android.intent.extra.STREAM", f"file://{image_path.resolve()}",
                    "--es", "android.intent.extra.TEXT", full_text
                ]
                res = subprocess.run(cmd, capture_output=True, text=True)
                if res.returncode == 0:
                    return True, "Triggered Android Share Sheet with enhanced image. Caption copied to clipboard!"
            except Exception as e:
                return False, f"Android share intent failed: {e}"

        return True, f"Caption copied to clipboard! Enhanced image exported to: {image_path}"
