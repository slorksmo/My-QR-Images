@echo off
chcp 65001 >nul
color 0A
echo ==================================================
echo       🚀 أداة الرفع السريع والتقصير - يا برنس!
echo ==================================================
echo.

:: إعدادات حسابك (تم إضافتها تلقائيا)
set USERNAME=slorksmo
set REPO=My-QR-Images

echo [1] جاري تحديث ورفع الصور الجديدة على GitHub...
git add .
git commit -m "Upload image via Automation Tool"
git push
echo ✅ تم الرفع بنجاح!
echo.

echo [2] جاري البحث عن أحدث صورة تم وضعها...
for /f "delims=" %%I in ('dir /b /a-d /o-d *.png *.jpg *.jpeg') do (
    set "NEWEST_FILE=%%I"
    goto :Found
)
:Found
echo 🖼️ الصورة الأحدث هي: %NEWEST_FILE%
echo.

:: معالجة المسافات في اسم الملف لضمان عمل الرابط
set "ENCODED_FILE=%NEWEST_FILE: =%%20%"
set "RAW_URL=https://raw.githubusercontent.com/%USERNAME%/%REPO%/main/%ENCODED_FILE%"

echo [3] جاري تقصير الرابط...
for /f "delims=" %%A in ('curl -s "https://is.gd/create.php?format=simple&url=%RAW_URL%"') do set SHORT_URL=%%A

echo.
echo ==================================================
echo 🎉 تمت العملية بنجاح!
echo 🔗 الرابط المختصر: %SHORT_URL%
echo ==================================================
echo.

:: نسخ الرابط للحافظة (Clipboard)
echo | set /p="%SHORT_URL%" | clip
echo ✂️ (تم نسخ الرابط، اضغط Paste في موقع الـ QR على طول!)
echo.
pause