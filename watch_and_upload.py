#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
watch_and_upload.py
====================
سكربت يراقب مجلدًا محددًا، وعند إضافة صورة جديدة:
  1. يرفعها تلقائيًا إلى مستودع GitHub (git add / commit / push)
  2. يبني رابط الوصول المباشر (Raw URL) للصورة على GitHub
  3. يرسل الرابط إلى خدمة Is.gd لاختصاره
  4. ينسخ الرابط المختصر تلقائيًا إلى الحافظة (Clipboard)
  5. يسجل كل خطوة (نجاح/فشل) في ملف Log

الاعتماديات المطلوبة (يتم تثبيتها مرة واحدة):
    pip install watchdog pyperclip requests --break-system-packages

ملاحظات تشغيل:
- يجب أن يكون المجلد الذي يُراقَب هو نفسه (أو مجلد فرعي من) مستودع Git مهيأ
  ومرتبط مسبقًا بـ remote باسم origin، وأن يكون لديك صلاحية push (SSH key أو
  Personal Access Token مُهيأ في بيئة git).
- على لينكس، نسخ الحافظة (pyperclip) يحتاج إلى وجود xclip أو xsel مثبتين:
    sudo apt-get install xclip
  أما على ويندوز وماك فهو يعمل دون أي إعداد إضافي.
"""

import os
import sys
import time
import logging
import subprocess
import urllib.parse
from pathlib import Path
from datetime import datetime

try:
    import requests
except ImportError:
    print("الحزمة 'requests' غير مثبتة. نفّذ: pip install requests --break-system-packages")
    sys.exit(1)

try:
    import pyperclip
except ImportError:
    print("الحزمة 'pyperclip' غير مثبتة. نفّذ: pip install pyperclip --break-system-packages")
    sys.exit(1)

try:
    from watchdog.observers import Observer
    from watchdog.events import FileSystemEventHandler
except ImportError:
    print("الحزمة 'watchdog' غير مثبتة. نفّذ: pip install watchdog --break-system-packages")
    sys.exit(1)


# =========================================================================
#                              ملف الإعدادات
# =========================================================================
# عدّل القيم التالية حسب بيئتك، أو مرّرها كمتغيرات بيئة (Environment Variables)
# مثال:
#   export WATCH_FOLDER="/home/user/Pictures/qr_images"
#   export GIT_REPO_PATH="/home/user/Pictures/qr_images"
#   export GITHUB_USERNAME="your-username"
#   export GITHUB_REPO="your-repo"
#   export GITHUB_BRANCH="main"

CONFIG = {
    # المجلد الذي سيتم مراقبته (يجب أن يكون داخل مستودع git محلي)
    "WATCH_FOLDER": os.environ.get("WATCH_FOLDER", "/home/user/Pictures/qr_images"),

    # مسار جذر مستودع git (غالبًا نفس المجلد أعلاه أو أحد آبائه)
    "GIT_REPO_PATH": os.environ.get("GIT_REPO_PATH", "/home/user/Pictures/qr_images"),

    # اسم المستخدم واسم المستودع على GitHub، لبناء رابط raw.githubusercontent.com
    "GITHUB_USERNAME": os.environ.get("GITHUB_USERNAME", "your-username"),
    "GITHUB_REPO": os.environ.get("GITHUB_REPO", "your-repo"),
    "GITHUB_BRANCH": os.environ.get("GITHUB_BRANCH", "main"),

    # المسار النسبي للمجلد المراقب داخل المستودع (اتركه "" إذا كان المجلد = جذر المستودع)
    # مثال: إذا كان مسار الصورة داخل المستودع repo/images/photo.png ضع "images"
    "REPO_SUBFOLDER": os.environ.get("REPO_SUBFOLDER", ""),

    # امتدادات الصور المقبولة
    "IMAGE_EXTENSIONS": {".png", ".jpg", ".jpeg", ".gif", ".bmp", ".webp", ".svg"},

    # مهلة انتظار (بالثواني) للتأكد أن الملف انتهى من الكتابة فعليًا على القرص
    "FILE_STABILITY_WAIT": 2,

    # عدد محاولات إعادة المحاولة عند فشل أي خطوة شبكية (push / is.gd)
    "MAX_RETRIES": 3,
    "RETRY_DELAY": 5,

    # مسار ملف السجل
    "LOG_FILE": os.environ.get("LOG_FILE", "./upload_log.log"),
}


# =========================================================================
#                              إعداد التسجيل (Logging)
# =========================================================================
def setup_logger() -> logging.Logger:
    logger = logging.getLogger("image_uploader")
    logger.setLevel(logging.DEBUG)

    formatter = logging.Formatter(
        fmt="%(asctime)s | %(levelname)-8s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    # ملف السجل
    file_handler = logging.FileHandler(CONFIG["LOG_FILE"], encoding="utf-8")
    file_handler.setFormatter(formatter)
    file_handler.setLevel(logging.DEBUG)

    # الطرفية (Console)
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(formatter)
    console_handler.setLevel(logging.INFO)

    logger.addHandler(file_handler)
    logger.addHandler(console_handler)
    return logger


logger = setup_logger()


# =========================================================================
#                         تنفيذ أوامر shell بأمان
# =========================================================================
def run_command(command: list, cwd: str, timeout: int = 60):
    """
    يشغّل أمر نظام (مثل git) ويعيد (success: bool, stdout: str, stderr: str)
    """
    try:
        result = subprocess.run(
            command,
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        if result.returncode == 0:
            return True, result.stdout.strip(), result.stderr.strip()
        else:
            return False, result.stdout.strip(), result.stderr.strip()
    except subprocess.TimeoutExpired:
        return False, "", f"انتهت المهلة الزمنية لتنفيذ الأمر: {' '.join(command)}"
    except FileNotFoundError:
        return False, "", f"الأمر غير موجود: {command[0]}"
    except Exception as e:
        return False, "", str(e)


def wait_until_file_is_stable(file_path: Path, wait_seconds: int) -> bool:
    """
    ينتظر حتى يستقر حجم الملف (يتأكد أن نسخ/إنشاء الصورة انتهى فعليًا)
    لتجنب رفع ملف غير مكتمل.
    """
    try:
        last_size = -1
        stable_checks = 0
        max_checks = 30  # حد أعلى للانتظار (~ wait_seconds * max_checks ثانية كحد أقصى)

        for _ in range(max_checks):
            if not file_path.exists():
                return False
            current_size = file_path.stat().st_size
            if current_size == last_size and current_size > 0:
                stable_checks += 1
                if stable_checks >= 2:
                    return True
            else:
                stable_checks = 0
            last_size = current_size
            time.sleep(wait_seconds)
        return file_path.exists()
    except Exception as e:
        logger.error(f"خطأ أثناء انتظار استقرار الملف {file_path}: {e}")
        return False


# =========================================================================
#                       الخطوة 1: رفع الصورة إلى GitHub
# =========================================================================
def git_add_commit_push(file_path: Path) -> bool:
    repo_path = CONFIG["GIT_REPO_PATH"]
    relative_path = file_path.relative_to(Path(repo_path).resolve())
    commit_message = f"Add image: {file_path.name} ({datetime.now().strftime('%Y-%m-%d %H:%M:%S')})"

    for attempt in range(1, CONFIG["MAX_RETRIES"] + 1):
        logger.info(f"[Git] محاولة #{attempt} لرفع الملف: {relative_path}")

        # git add
        ok, out, err = run_command(["git", "add", str(relative_path)], cwd=repo_path)
        if not ok:
            logger.error(f"[Git] فشل git add: {err}")
            time.sleep(CONFIG["RETRY_DELAY"])
            continue

        # git commit (قد يفشل إن لم يوجد تغيير فعلي، نتعامل مع هذا بشكل خاص)
        ok, out, err = run_command(["git", "commit", "-m", commit_message], cwd=repo_path)
        if not ok:
            if "nothing to commit" in (out + err).lower():
                logger.warning("[Git] لا يوجد تغيير جديد للـ commit، يبدو أن الملف مرفوع مسبقًا.")
                return True
            logger.error(f"[Git] فشل git commit: {err}")
            time.sleep(CONFIG["RETRY_DELAY"])
            continue

        logger.info(f"[Git] تم الـ commit بنجاح: {commit_message}")

        # git push
        ok, out, err = run_command(
            ["git", "push", "origin", CONFIG["GITHUB_BRANCH"]], cwd=repo_path, timeout=120
        )
        if not ok:
            logger.error(f"[Git] فشل git push: {err}")
            time.sleep(CONFIG["RETRY_DELAY"])
            continue

        logger.info(f"[Git] تم رفع الصورة (push) بنجاح إلى الفرع {CONFIG['GITHUB_BRANCH']}")
        return True

    logger.error(f"[Git] فشل رفع الملف {file_path.name} بعد {CONFIG['MAX_RETRIES']} محاولات.")
    return False


# =========================================================================
#                  الخطوة 2: بناء رابط الصورة المباشر على GitHub
# =========================================================================
def build_github_raw_url(file_path: Path) -> str:
    repo_path = Path(CONFIG["GIT_REPO_PATH"]).resolve()
    relative_path = file_path.relative_to(repo_path)

    subfolder = CONFIG["REPO_SUBFOLDER"].strip("/")
    if subfolder:
        full_relative = f"{subfolder}/{relative_path.as_posix()}"
    else:
        full_relative = relative_path.as_posix()

    # ترميز المسار للتعامل مع المسافات والحروف العربية وغيرها
    encoded_path = urllib.parse.quote(full_relative)

    url = (
        f"https://raw.githubusercontent.com/"
        f"{CONFIG['GITHUB_USERNAME']}/{CONFIG['GITHUB_REPO']}/"
        f"{CONFIG['GITHUB_BRANCH']}/{encoded_path}"
    )
    logger.info(f"[URL] الرابط المباشر للصورة: {url}")
    return url


# =========================================================================
#                  الخطوة 3: اختصار الرابط عبر خدمة Is.gd
# =========================================================================
def shorten_url_isgd(long_url: str) -> str:
    api_endpoint = "https://is.gd/create.php"
    params = {"format": "simple", "url": long_url}

    for attempt in range(1, CONFIG["MAX_RETRIES"] + 1):
        try:
            logger.info(f"[Is.gd] محاولة #{attempt} لاختصار الرابط...")
            response = requests.get(api_endpoint, params=params, timeout=15)
            response.raise_for_status()
            short_url = response.text.strip()

            if short_url.startswith("https://is.gd/") or short_url.startswith("http://is.gd/"):
                logger.info(f"[Is.gd] تم اختصار الرابط بنجاح: {short_url}")
                return short_url
            else:
                # is.gd يعيد رسالة خطأ نصية بدل الرابط في حال الفشل
                logger.error(f"[Is.gd] استجابة غير متوقعة من الخدمة: {short_url}")
        except requests.exceptions.RequestException as e:
            logger.error(f"[Is.gd] فشل الاتصال بخدمة الاختصار: {e}")

        time.sleep(CONFIG["RETRY_DELAY"])

    logger.error("[Is.gd] فشل اختصار الرابط بعد عدة محاولات. سيتم استخدام الرابط الكامل كحل احتياطي.")
    return long_url


# =========================================================================
#                  الخطوة 4: نسخ الرابط إلى الحافظة (Clipboard)
# =========================================================================
def copy_to_clipboard(text: str) -> bool:
    try:
        pyperclip.copy(text)
        logger.info(f"[Clipboard] تم نسخ الرابط إلى الحافظة: {text}")
        return True
    except Exception as e:
        logger.error(f"[Clipboard] فشل النسخ إلى الحافظة: {e}")
        logger.error(
            "تلميح: على لينكس قد تحتاج إلى تثبيت xclip أو xsel "
            "(sudo apt-get install xclip)."
        )
        return False


# =========================================================================
#                         المعالج الرئيسي لكل صورة جديدة
# =========================================================================
def process_new_image(file_path: Path):
    logger.info(f"==> تم رصد ملف جديد: {file_path}")

    # 1) التأكد أن الملف صورة بالامتداد المطلوب
    if file_path.suffix.lower() not in CONFIG["IMAGE_EXTENSIONS"]:
        logger.debug(f"تجاهل الملف (ليس صورة مدعومة): {file_path.name}")
        return

    # 2) الانتظار حتى يستقر الملف (انتهاء الكتابة/النسخ)
    if not wait_until_file_is_stable(file_path, CONFIG["FILE_STABILITY_WAIT"]):
        logger.error(f"الملف غير مستقر أو تم حذفه قبل المعالجة: {file_path}")
        return

    try:
        # 3) رفع الصورة إلى GitHub
        if not git_add_commit_push(file_path):
            logger.error(f"تم إيقاف المعالجة بسبب فشل رفع الصورة: {file_path.name}")
            return

        # 4) بناء الرابط المباشر
        raw_url = build_github_raw_url(file_path)

        # 5) اختصار الرابط
        short_url = shorten_url_isgd(raw_url)

        # 6) نسخ الرابط المختصر إلى الحافظة
        copy_to_clipboard(short_url)

        logger.info(f"==> اكتملت معالجة الصورة بنجاح: {file_path.name} -> {short_url}\n")

    except Exception as e:
        logger.exception(f"حدث خطأ غير متوقع أثناء معالجة الصورة {file_path.name}: {e}")


# =========================================================================
#                       مراقب المجلد (Watchdog Handler)
# =========================================================================
class ImageHandler(FileSystemEventHandler):
    def on_created(self, event):
        if event.is_directory:
            return
        file_path = Path(event.src_path)
        process_new_image(file_path)

    def on_moved(self, event):
        # في حال تم نقل/إعادة تسمية صورة إلى المجلد المراقب
        if event.is_directory:
            return
        file_path = Path(event.dest_path)
        process_new_image(file_path)


# =========================================================================
#                              نقطة البدء
# =========================================================================
def validate_config():
    errors = []

    watch_folder = Path(CONFIG["WATCH_FOLDER"])
    repo_path = Path(CONFIG["GIT_REPO_PATH"])

    if not watch_folder.exists():
        errors.append(f"المجلد المراقب غير موجود: {watch_folder}")

    if not repo_path.exists():
        errors.append(f"مسار مستودع git غير موجود: {repo_path}")
    else:
        if not (repo_path / ".git").exists():
            errors.append(f"المسار المحدد ليس جذر مستودع git صالح: {repo_path}")

    if CONFIG["GITHUB_USERNAME"] == "your-username" or CONFIG["GITHUB_REPO"] == "your-repo":
        errors.append("يجب تعديل GITHUB_USERNAME و GITHUB_REPO في الإعدادات قبل التشغيل.")

    try:
        watch_resolved = watch_folder.resolve()
        repo_resolved = repo_path.resolve()
        watch_resolved.relative_to(repo_resolved)
    except ValueError:
        errors.append("المجلد المراقب (WATCH_FOLDER) يجب أن يكون داخل مستودع git (GIT_REPO_PATH).")

    return errors


def main():
    logger.info("=" * 70)
    logger.info("بدء تشغيل سكربت مراقبة ورفع الصور")
    logger.info(f"المجلد المراقب: {CONFIG['WATCH_FOLDER']}")
    logger.info(f"مستودع git: {CONFIG['GIT_REPO_PATH']}")
    logger.info("=" * 70)

    config_errors = validate_config()
    if config_errors:
        for err in config_errors:
            logger.error(f"[إعدادات] {err}")
        logger.error("يرجى تصحيح الإعدادات أعلاه (في رأس الملف أو عبر متغيرات البيئة) ثم إعادة التشغيل.")
        sys.exit(1)

    event_handler = ImageHandler()
    observer = Observer()
    observer.schedule(event_handler, CONFIG["WATCH_FOLDER"], recursive=True)
    observer.start()

    logger.info("المراقبة جارية... (اضغط Ctrl+C للإيقاف)")

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        logger.info("تم استلام أمر الإيقاف من المستخدم (Ctrl+C).")
        observer.stop()
    except Exception as e:
        logger.exception(f"خطأ غير متوقع في الحلقة الرئيسية: {e}")
        observer.stop()
    finally:
        observer.join()
        logger.info("تم إيقاف المراقبة. إنهاء البرنامج.")


if __name__ == "__main__":
    main()
