from flask import (
    Flask,
    redirect,
    request,
    render_template,
    send_from_directory,
    session,
    url_for,
)
from werkzeug.middleware.proxy_fix import ProxyFix
from werkzeug.utils import secure_filename
from pdfCropMargins import crop
import atexit
import os
import secrets
import shutil
import subprocess
import tempfile
from uuid import uuid4
import zipfile


BASE_FOLDER = tempfile.mkdtemp(prefix="pdf_crop-")
app = Flask(__name__)
app.config["BASE_FOLDER"] = BASE_FOLDER
app.config["SECRET_KEY"] = secrets.token_urlsafe(32)
atexit.register(shutil.rmtree, BASE_FOLDER)


@app.route("/")
def index():
    if not os.path.exists(os.path.join(app.config["BASE_FOLDER"], session.get('sid', 'None'))):
        session["msg"] = ""
        session["num_page"] = 0
        session.pop("data", None)
    msg = session.get("msg", "")
    num_page = session.get("num_page", 0)
    data = session.get("data", {})
    return render_template("index.html", message=msg, num_page=num_page, data=data)


@app.route("/upload", methods=["POST"])
def upload_file():
    session["num_page"] = 0
    session.pop("data", None)
    if "file" not in request.files:
        session["msg"] = "No file part"
        return redirect(url_for("index"))

    file = request.files["file"]
    if not file or file.filename == "":
        session["msg"] = "No selected file"
        return redirect(url_for("index"))

    # create a new session
    sid = str(uuid4())
    os.makedirs(os.path.join(app.config["BASE_FOLDER"], sid, "upload"), exist_ok=True)
    os.makedirs(os.path.join(app.config["BASE_FOLDER"], sid, "split"), exist_ok=True)
    os.makedirs(os.path.join(app.config["BASE_FOLDER"], sid, "download"), exist_ok=True)
    session["sid"] = sid
    # upload the file
    filename_base = secure_filename(file.filename)
    session["filename_base"] = filename_base
    filename = os.path.join(app.config["BASE_FOLDER"], sid, "upload", filename_base)
    file.save(filename)
    # extract num_page
    proc = subprocess.run(["pdftk", filename, "dump_data"], capture_output=True)
    num_page = 0
    for line in proc.stdout.decode().splitlines():
        if line.startswith("NumberOfPages"):
            num_page = int(line.split()[-1])
            break
    if num_page == 0:
        session["msg"] = "No page found"
        return redirect(url_for("index"))
    session["num_page"] = num_page
    session["msg"] = f"File '{filename_base}' has {num_page} pages."
    return redirect(url_for("index"))


@app.route("/process", methods=["POST"])
def process_pages():
    filename_base = secure_filename(session["filename_base"])
    filename_noext = filename_base.removesuffix(".pdf")
    sid = session["sid"]
    SPLIT_FOLDER = os.path.join(app.config["BASE_FOLDER"], sid, "split")
    PROCESSED_FOLDER = os.path.join(app.config["BASE_FOLDER"], sid, "download")
    selected_pages = request.form.getlist("selected_pages")
    selected_pages_ids = [int(page.split()[-1]) for page in selected_pages]
    procs = [
        subprocess.Popen(
            [
                "pdftk",
                os.path.join(app.config["BASE_FOLDER"], sid, "upload", filename_base),
                "cat",
                f"{page_id}-{page_id}",
                "output",
                os.path.join(SPLIT_FOLDER, f"{filename_noext}_{page_id}.pdf"),
            ]
        )
        for page_id in selected_pages_ids
    ]
    filenames = request.form.get("filenames")
    num_page = session["num_page"]
    pages_n = [None] + [
        f"{filename_noext}_{page_id}.pdf" for page_id in range(num_page)
    ]
    for i, fname in enumerate(filenames.splitlines()[:num_page]):
        if fname:
            pages_n[i + 1] = secure_filename(fname) + ".pdf"
    selected_pages_n = [pages_n[page_id] for page_id in selected_pages_ids]
    for proc, page_id, page_n in zip(procs, selected_pages_ids, selected_pages_n):
        proc.wait()
        crop(
            [
                "-v",
                "-s",
                "-u",
                "-p",
                "0",
                "-a",
                "0",
                os.path.join(SPLIT_FOLDER, f"{filename_noext}_{page_id}.pdf"),
                "-o",
                os.path.join(PROCESSED_FOLDER, page_n),
            ]
        )
    if len(selected_pages_n) > 1:
        with zipfile.ZipFile(
            os.path.join(PROCESSED_FOLDER, f"{filename_noext}.zip"),
            "w",
            zipfile.ZIP_DEFLATED,
        ) as zipf:
            for page_n in selected_pages_n:
                zipf.write(os.path.join(PROCESSED_FOLDER, page_n), page_n)
    session["data"] = {"fn": filename_noext, "selected_pages_n": selected_pages_n}
    session["msg"] = "Success"
    return redirect(url_for("index"))


@app.route("/download/<filename>")
def download_file(filename):
    sid = session["sid"]
    filename = secure_filename(filename)
    print("download", filename)
    PROCESSED_FOLDER = os.path.join(app.config["BASE_FOLDER"], sid, "download")
    return send_from_directory(PROCESSED_FOLDER, filename, as_attachment=True)


if __name__ == "__main__":
    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_prefix=1)
    app.run(port=8086)
