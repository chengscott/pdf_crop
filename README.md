# PDF Crop

## Install

- [pdftk](https://archlinux.org/packages/extra/any/pdftk) package

```
pip install -r requirements.txt
```

## Run

```
SCRIPT_NAME=/pdf gunicorn --bind 127.0.0.1:8086 app:app
```
