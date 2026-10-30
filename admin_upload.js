const dropZone = document.getElementById("drop-zone");
const uploadInput = document.getElementById("id_file");
const fileName = document.getElementById("file-name");
const filePrompt = document.getElementById("file-prompt");

function showSelectedFile(file) {
    if (!file) return;
    fileName.textContent = `${file.name} · ${(file.size / 1024 / 1024).toFixed(1)} MB`;
    filePrompt.textContent = "선택된 파일";
    dropZone.classList.add("has-file");
}

uploadInput.addEventListener("change", () => showSelectedFile(uploadInput.files[0]));
dropZone.addEventListener("keydown", (event) => {
    if (event.key === "Enter" || event.key === " ") {
        event.preventDefault();
        uploadInput.click();
    }
});
for (const eventName of ["dragenter", "dragover"]) {
    dropZone.addEventListener(eventName, (event) => {
        event.preventDefault();
        dropZone.classList.add("is-dragging");
    });
}
for (const eventName of ["dragleave", "drop"]) {
    dropZone.addEventListener(eventName, (event) => {
        event.preventDefault();
        dropZone.classList.remove("is-dragging");
    });
}
dropZone.addEventListener("drop", (event) => {
    const [file] = event.dataTransfer.files;
    if (!file) return;
    const transfer = new DataTransfer();
    transfer.items.add(file);
    uploadInput.files = transfer.files;
    showSelectedFile(file);
});