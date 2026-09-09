(() => {
  const zone = document.getElementById("report-drop-zone");
  const input = document.getElementById("report-files");
  if (!zone || !input) return;

  const status = document.getElementById("report-files-status");
  const list = document.getElementById("report-files-list");
  let dragDepth = 0;
  const isFileDrag = (event) => Array.from(event.dataTransfer?.types || []).includes("Files");
  const resetDrag = () => {
    dragDepth = 0;
    zone.classList.remove("is-dragging");
  };

  input.addEventListener("change", () => {
    list.replaceChildren();
    for (const file of input.files) {
      const item = document.createElement("li");
      item.textContent = file.name;
      list.appendChild(item);
    }
    status.textContent = input.files.length
      ? `Выбрано файлов: ${input.files.length}. Нажмите «Загрузить выбранные файлы».`
      : "";
  });

  zone.addEventListener("dragenter", (event) => {
    if (!isFileDrag(event)) return;
    event.preventDefault();
    dragDepth += 1;
    zone.classList.add("is-dragging");
  });
  zone.addEventListener("dragover", (event) => {
    if (!isFileDrag(event)) return;
    event.preventDefault();
    event.dataTransfer.dropEffect = "copy";
  });
  zone.addEventListener("dragleave", () => {
    dragDepth = Math.max(0, dragDepth - 1);
    if (!dragDepth) resetDrag();
  });
  zone.addEventListener("drop", (event) => {
    event.preventDefault();
    resetDrag();
    const files = Array.from(event.dataTransfer?.files || []);
    const entries = Array.from(event.dataTransfer?.items || []);
    if (entries.some((item) => item.webkitGetAsEntry?.()?.isDirectory)) {
      status.textContent = "Перетащите сами файлы отчетов, а не папку.";
      return;
    }
    if (!files.length) {
      status.textContent = "Файлы не найдены. Используйте кнопку выбора файлов.";
      return;
    }
    try {
      const transfer = new DataTransfer();
      files.forEach((file) => transfer.items.add(file));
      input.files = transfer.files;
      input.dispatchEvent(new Event("change", { bubbles: true }));
    } catch {
      status.textContent = "Браузер не поддерживает перетаскивание. Используйте кнопку выбора файлов.";
    }
  });
  document.addEventListener("dragend", resetDrag);
  // Prevent the browser from navigating away when files miss the upload area.
  for (const type of ["dragover", "drop"]) {
    document.addEventListener(type, (event) => {
      if (isFileDrag(event)) event.preventDefault();
      if (type === "drop") resetDrag();
    });
  }
})();
