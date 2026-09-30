(() => {
  const chat = document.getElementById("chat");
  const form = document.getElementById("chat-form");
  const input = document.getElementById("msg");
  const photoInput = document.getElementById("photo");
  const photoName = document.getElementById("photo-name");
  const sendBtn = document.getElementById("send");
  const typing = document.getElementById("typing");
  const quickstart = document.getElementById("quickstart");
  const slug = location.pathname.split("/").pop();

  let pendingPhoto = null;
  let busy = false;

  const scrollBottom = () => requestAnimationFrame(() => {
    chat.scrollTop = chat.scrollHeight;
  });

  function addMsg(role, text, withPhoto) {
    const div = document.createElement("div");
    div.className = "msg " + (role === "user" ? "user" : "bot");
    if (withPhoto) {
      const flag = document.createElement("span");
      flag.className = "photo-flag";
      flag.textContent = "📷 photo du cahier";
      div.appendChild(flag);
    }
    div.appendChild(document.createTextNode(text));
    chat.appendChild(div);
    scrollBottom();
    return div;
  }

  async function loadHistory() {
    try {
      const res = await fetch(`/api/chat/${slug}/history`);
      if (!res.ok) throw new Error();
      const data = await res.json();
      for (const m of data.messages) {
        addMsg(m.role, m.content, false);
      }
      if (data.messages.length === 0) quickstart.classList.remove("hidden");
    } catch {
      addMsg("bot", "Impossible de charger l'historique. Recharge la page.");
    }
  }

  function setBusy(state) {
    busy = state;
    sendBtn.disabled = state;
    input.disabled = state;
    photoInput.disabled = state;
    typing.classList.toggle("hidden", !state);
    if (!state) scrollBottom();
  }

  async function send(message, photoFile) {
    if (busy) return;
    setBusy(true);
    addMsg("user", message || "Voici une photo de mon cahier.", !!photoFile);
    quickstart.classList.add("hidden");

    const fd = new FormData();
    fd.append("message", message || "");
    if (photoFile) fd.append("image", photoFile);

    const botDiv = addMsg("bot", "");
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
              botDiv.textContent = botText;
              scrollBottom();
            } else if (ev.type === "done") {
              botText = ev.content || botText;
              botDiv.textContent = botText;
            } else if (ev.type === "error") {
              botDiv.textContent = ev.content;
              botDiv.classList.add("error-line");
            }
          } catch { /* chunk partiel */ }
        }
      }
    } catch {
      if (!botText) botDiv.textContent = "Erreur de connexion. Réessaie dans un instant.";
    } finally {
      setBusy(false);
      pendingPhoto = null;
      photoName.classList.add("hidden");
      photoName.textContent = "";
      input.value = "";
      input.focus();
    }
  }

  form.addEventListener("submit", (e) => {
    e.preventDefault();
    const message = input.value.trim();
    if (!message && !pendingPhoto) return;
    send(message, pendingPhoto);
  });

  photoInput.addEventListener("change", () => {
    if (photoInput.files.length) {
      setPendingPhoto(photoInput.files[0]);
    }
  });

  function setPendingPhoto(file) {
    if (!file || !file.type.startsWith("image/")) return;
    pendingPhoto = file;
    const label = file.name && file.name !== "image.png"
      ? file.name
      : "capture d'écran";
    photoName.textContent = "📷 " + label + " — prête à envoyer";
    photoName.classList.remove("hidden");
  }

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

  quickstart.querySelectorAll("button").forEach((btn) => {
    btn.addEventListener("click", () => send(btn.dataset.msg, null));
  });

  loadHistory();
})();
