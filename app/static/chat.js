(() => {
  const chat = document.getElementById("chat");
  const form = document.getElementById("chat-form");
  const input = document.getElementById("msg");
  const photoInput = document.getElementById("photo");
  const sendBtn = document.getElementById("send");
  const quickstart = document.getElementById("quickstart");
  const photoRemove = document.getElementById("photo-remove");
  const photoPreview = document.getElementById("photo-preview");
  const photoPreviewImg = document.getElementById("photo-preview-img");
  const slug = location.pathname.split("/").pop();

  let photoObjectUrl = null;

  let pendingPhoto = null;
  let busy = false;

  const scrollBottom = () => requestAnimationFrame(() => {
    chat.scrollTop = chat.scrollHeight;
  });

  function renderRich(el, text) {
    el.innerHTML = marked.parse(text);
    el.querySelectorAll("p").forEach((p) => {
      if (!p.textContent.trim()) p.remove();
    });
    if (window.renderMathInElement) {
      window.renderMathInElement(el, {
        delimiters: [
          { left: "$$", right: "$$", display: true },
          { left: "\\(", right: "\\)", display: false },
          { left: "$", right: "$", display: false },
        ],
        throwOnError: false,
      });
    }
  }

  function addMsg(role, text, imageUrl) {
    const div = document.createElement("div");
    div.className = "msg " + (role === "user" ? "user" : "bot");
    if (imageUrl) {
      const thumb = document.createElement("img");
      thumb.className = "msg-photo";
      thumb.src = imageUrl;
      thumb.alt = "photo du cahier";
      div.appendChild(thumb);
    }
    const body = document.createElement("div");
    body.className = "msg-body";
    if (role === "bot") {
      renderRich(body, text);
    } else {
      body.textContent = text;
    }
    div.appendChild(body);
    chat.appendChild(div);
    scrollBottom();
    return body;
  }

  async function loadHistory() {
    try {
      const res = await fetch(`/api/chat/${slug}/history`);
      if (!res.ok) throw new Error();
      const data = await res.json();
      for (const m of data.messages) {
        const url = m.has_image && m.id
          ? `/api/chat/${slug}/image/${m.id}`
          : null;
        addMsg(m.role, m.content, url);
      }
      if (data.messages.length === 0) quickstart.classList.remove("hidden");
    } catch {
      addMsg("bot", "Impossible de charger l'historique. Recharge la page.");
    }
  }

  let typingEl = null;

  function showTyping() {
    hideTyping();
    typingEl = document.createElement("div");
    typingEl.className = "typing";
    typingEl.innerHTML = "<span></span><span></span><span></span>";
    chat.appendChild(typingEl);
    scrollBottom();
  }

  function hideTyping() {
    if (typingEl) {
      typingEl.remove();
      typingEl = null;
    }
  }

  function setBusy(state) {
    busy = state;
    sendBtn.disabled = state;
    input.disabled = state;
    photoInput.disabled = state;
    if (state) showTyping(); else hideTyping();
    if (!state) scrollBottom();
  }

  async function send(message, photoFile) {
    if (busy) return;
    addMsg("user", message || "Voici une photo de mon cahier.", photoObjectUrl);
    clearPendingPhoto();
    setBusy(true);
    quickstart.classList.add("hidden");

    const fd = new FormData();
    fd.append("message", message || "");
    if (photoFile) fd.append("image", photoFile);

    const botBody = addMsg("bot", "");
    let botText = "";

    try {
      const res = await fetch(`/api/chat/${slug}`, { method: "POST", body: fd });
      if (res.status === 401) { location.href = "/login?next=" + encodeURIComponent(location.pathname); return; }
      if (!res.ok) throw new Error();

      const reader = res.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        let idx;
        while ((idx = buffer.indexOf("\n\n")) !== -1) {
          const raw = buffer.slice(0, idx);
          buffer = buffer.slice(idx + 2);
          if (!raw.startsWith("data: ")) continue;
          try {
            const ev = JSON.parse(raw.slice(6));
            if (ev.type === "token") {
              botText += ev.content;
              renderRich(botBody, botText);
              scrollBottom();
            } else if (ev.type === "done") {
              botText = ev.content || botText;
              renderRich(botBody, botText);
            } else if (ev.type === "error") {
              botBody.textContent = ev.content;
              botBody.classList.add("error-line");
            }
          } catch { /* chunk partiel */ }
        }
      }
    } catch {
      if (!botText) botBody.textContent = "Erreur de connexion. Réessaie dans un instant.";
    } finally {
      setBusy(false);
      input.value = "";
      autoResize();
      input.focus();
    }
  }

  form.addEventListener("submit", (e) => {
    e.preventDefault();
    const message = input.value.trim();
    if (!message && !pendingPhoto) return;
    send(message, pendingPhoto);
  });

  function autoResize() {
    input.style.height = "auto";
    input.style.height = Math.min(input.scrollHeight, 160) + "px";
  }

  input.addEventListener("input", autoResize);

  input.addEventListener("keydown", (e) => {
    if (e.key === "Enter" && !e.shiftKey && !e.isComposing) {
      e.preventDefault();
      form.requestSubmit();
    }
  });

  photoInput.addEventListener("change", () => {
    if (photoInput.files.length) {
      setPendingPhoto(photoInput.files[0]);
    }
  });

  function setPendingPhoto(file) {
    if (!file || !file.type.startsWith("image/")) return;
    pendingPhoto = file;
    if (photoObjectUrl) URL.revokeObjectURL(photoObjectUrl);
    photoObjectUrl = URL.createObjectURL(file);
    photoPreviewImg.src = photoObjectUrl;
    photoPreview.classList.remove("hidden");
  }

  function clearPendingPhoto() {
    pendingPhoto = null;
    photoInput.value = "";
    if (photoObjectUrl) {
      URL.revokeObjectURL(photoObjectUrl);
      photoObjectUrl = null;
    }
    photoPreviewImg.src = "";
    photoPreview.classList.add("hidden");
  }

  photoRemove.addEventListener("click", clearPendingPhoto);

  document.addEventListener("paste", (e) => {
    if (busy) return;
    const items = e.clipboardData && e.clipboardData.items;
    if (!items) return;
    for (const item of items) {
      if (item.type && item.type.startsWith("image/")) {
        const file = item.getAsFile();
        if (file) {
          e.preventDefault();
          setPendingPhoto(file);
          input.focus();
        }
        return;
      }
    }
  });

  const resetBtn = document.getElementById("reset-chat");
  if (resetBtn) {
    resetBtn.addEventListener("click", async () => {
      if (busy) return;
      if (!confirm("Recommencer la conversation ? L'historique sera effacé.")) return;
      try {
        const res = await fetch(`/api/chat/${slug}/reset`, { method: "POST" });
        if (!res.ok) throw new Error();
        chat.textContent = "";
        quickstart.classList.remove("hidden");
      } catch {
        addMsg("bot", "Impossible de réinitialiser la conversation. Recharge la page.");
      }
    });
  }

  quickstart.querySelectorAll("button").forEach((btn) => {
    btn.addEventListener("click", () => send(btn.dataset.msg, null));
  });

  loadHistory();
})();
