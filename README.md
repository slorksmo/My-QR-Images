# سكربت مراقبة ورفع الصور التلقائي

## ماذا يفعل؟
يراقب مجلدًا محليًا، وعند ظهور صورة جديدة فيه:
1. `git add` + `git commit` + `git push` للصورة إلى GitHub.
2. يبني رابط الوصول المباشر (raw.githubusercontent.com) للصورة.
3. يرسل الرابط إلى **Is.gd** لاختصاره.
4. ينسخ الرابط المختصر تلقائيًا إلى الحافظة (Clipboard) — جاهز للصق في أي
   موقع لإنشاء QR Code.
5. يسجّل كل خطوة (نجاح/فشل) في ملف `upload_log.log`.

## 1) التثبيت

```bash
pip install -r requirements.txt --break-system-packages
```

على لينكس، نسخ الحافظة يحتاج أيضًا إلى:
```bash
sudo apt-get install xclip
```

## 2) التهيئة المسبقة (مرة واحدة)

تأكد أن مجلد الصور هو نفسه (أو داخل) مستودع git مرتبط بـ GitHub ولديك صلاحية
push بدون كلمة مرور تفاعلية (SSH key أو Git Credential Manager / PAT محفوظ):

```bash
cd /path/to/your/repo
git remote -v          # تأكد من وجود origin
git push origin main   # جرّب رفع تجريبي يدوي أولًا للتأكد من الصلاحيات
```

## 3) ضبط الإعدادات

عدّل القيم مباشرة داخل ملف `watch_and_upload.py` (قسم `CONFIG` في الأعلى)
أو مرّرها كمتغيرات بيئة قبل التشغيل:

```bash
export WATCH_FOLDER="D:\Git Mo\My-QR-Images"
export GIT_REPO_PATH="D:\Git Mo\My-QR-Images"
export GITHUB_USERNAME="slorksmo"
export GITHUB_REPO="https://github.com/slorksmo/My-QR-Images.git"
export GITHUB_BRANCH="main"
```

> ملاحظة: إن كان مجلد الصور مجلدًا فرعيًا داخل المستودع (مثل `repo/images`)
> اضبط `REPO_SUBFOLDER` بالقيمة المناسبة، أو اجعل `GIT_REPO_PATH` يساوي
> مسار جذر المستودع بينما `WATCH_FOLDER` يساوي المسار الفرعي.

## 4) التشغيل

```bash
python3 watch_and_upload.py
```

اتركه يعمل في الخلفية (مثلًا داخل `tmux`/`screen`، أو كـ systemd service،
أو كـ Scheduled Task على ويندوز) ليستمر بالمراقبة. أوقفه بـ `Ctrl+C`.

## 5) السجل (Log)

كل العمليات — رفع git، بناء الرابط، الاختصار، النسخ، وأي أخطاء — تُسجَّل
بالتفصيل مع الوقت في `upload_log.log` بجانب السكربت.

## ملاحظات هامة
- السكربت ينتظر استقرار حجم الملف قبل المعالجة لتجنب رفع صورة لم يكتمل نسخها.
- في حال فشل `git push` أو خدمة `Is.gd`، يعاد المحاولة تلقائيًا (3 مرات
  بفارق 5 ثوانٍ) قبل تسجيل الفشل النهائي في اللوج.
- إذا فشل اختصار الرابط نهائيًا، يُستخدم الرابط الكامل كحل احتياطي بدل
  توقف العملية.
