const form = document.querySelector("#chat-form");
const input = document.querySelector("#message-input");
const sendButton = document.querySelector("#send-button");
const messages = document.querySelector("#messages");
const clearButton = document.querySelector("#clear-chat");
const traceDrawer = document.querySelector("#trace-drawer");
const traceContent = document.querySelector("#trace-content");

const welcomeMarkup = messages.innerHTML;
let isLoading = false;

function escapeText(value) {
  return String(value ?? "");
}

function scrollToBottom() {
  messages.scrollTo({ top: messages.scrollHeight, behavior: "smooth" });
}

function resizeInput() {
  input.style.height = "auto";
  input.style.height = `${Math.min(input.scrollHeight, 110)}px`;
}

function addUserMessage(text) {
  const article = document.createElement("article");
  article.className = "message user-message";
  const content = document.createElement("div");
  content.className = "message-content";
  const paragraph = document.createElement("p");
  paragraph.textContent = text;
  content.append(paragraph);
  article.append(content);
  messages.append(article);
}

function addAssistantMessage(text) {
  const article = document.createElement("article");
  article.className = "message assistant-message";
  const avatar = document.createElement("div");
  avatar.className = "assistant-avatar";
  avatar.setAttribute("aria-hidden", "true");
  avatar.textContent = "G";
  const content = document.createElement("div");
  content.className = "message-content";
  const paragraph = document.createElement("p");
  paragraph.textContent = text;
  content.append(paragraph);
  article.append(avatar, content);
  messages.append(article);
}

function addLoadingMessage() {
  const article = document.createElement("article");
  article.className = "message assistant-message loading-message";
  article.id = "loading-message";
  article.innerHTML = `
    <div class="assistant-avatar" aria-hidden="true">G</div>
    <div class="message-content">
      <p class="loading-title">Mình đang tìm món quà phù hợp...</p>
      <div class="loading-track"></div>
      <p class="loading-step">Đang phân tích sở thích và ngân sách</p>
    </div>
  `;
  messages.append(article);

  const steps = [
    "Đang phân tích sở thích và ngân sách",
    "Đang mở rộng các nhóm quà phù hợp",
    "Đang tìm sản phẩm và so sánh giá",
    "Đang chọn những gợi ý tốt nhất",
  ];
  let index = 0;
  const timer = window.setInterval(() => {
    const stepNode = article.querySelector(".loading-step");
    if (!stepNode || !article.isConnected) {
      window.clearInterval(timer);
      return;
    }
    index = Math.min(index + 1, steps.length - 1);
    stepNode.textContent = steps[index];
  }, 3800);
  article.dataset.timer = String(timer);
}

function removeLoadingMessage() {
  const loading = document.querySelector("#loading-message");
  if (!loading) return;
  window.clearInterval(Number(loading.dataset.timer));
  loading.remove();
}

function makePlaceholder() {
  const placeholder = document.createElement("div");
  placeholder.className = "product-image-placeholder";
  placeholder.innerHTML = `
    <svg viewBox="0 0 48 48" aria-hidden="true">
      <path d="M8 20h32v22H8zM5 14h38v8H5zM24 14v28"/>
      <path d="M14 14c-4-3.8-1.2-8.5 2.7-8C21.5 6.5 24 14 24 14M34 14c4-3.8 1.2-8.5-2.7-8C26.5 6.5 24 14 24 14"/>
    </svg>
  `;
  return placeholder;
}

function makeProductCard(product) {
  const card = document.createElement("article");
  card.className = "product-card";

  const media = document.createElement("div");
  media.className = "product-media";
  const placeholder = makePlaceholder();
  media.append(placeholder);

  if (product.image_url) {
    const image = document.createElement("img");
    image.src = product.image_url;
    image.alt = escapeText(product.name);
    image.loading = "lazy";
    image.referrerPolicy = "no-referrer";
    image.addEventListener("load", () => placeholder.remove());
    image.addEventListener("error", () => image.remove());
    media.append(image);
  }

  if (product.source) {
    const source = document.createElement("span");
    source.className = "source-badge";
    source.textContent = product.source;
    media.append(source);
  }

  const body = document.createElement("div");
  body.className = "product-body";

  const name = document.createElement("h4");
  name.className = "product-name";
  name.textContent = product.name;

  const price = document.createElement("p");
  price.className = "product-price";
  price.textContent = product.price_label;

  const reason = document.createElement("p");
  reason.className = "product-reason";
  reason.textContent = product.reason || "Một lựa chọn phù hợp để cân nhắc.";

  const link = document.createElement("a");
  link.className = "product-link";
  link.href = product.url;
  link.target = "_blank";
  link.rel = "noopener noreferrer";
  link.innerHTML = "<span>Xem sản phẩm</span><span aria-hidden='true'>↗</span>";

  body.append(name, price, reason, link);
  card.append(media, body);
  return card;
}

function addResults(result) {
  addAssistantMessage(result.message || "Mình đã tìm xong các gợi ý cho bạn.");

  const block = document.createElement("section");
  block.className = "result-block";

  const heading = document.createElement("div");
  heading.className = "result-heading";
  const title = document.createElement("h3");
  title.textContent = "Gợi ý dành cho bạn";
  const count = document.createElement("span");
  count.className = "result-count";
  count.textContent = `${result.products.length} sản phẩm`;
  heading.append(title, count);
  block.append(heading);

  if (result.products.length) {
    const grid = document.createElement("div");
    grid.className = "product-grid";
    result.products.forEach((item) => grid.append(makeProductCard(item)));
    block.append(grid);
  }

  const meta = document.createElement("div");
  meta.className = "result-meta";
  const budget = document.createElement("span");
  budget.className = "meta-chip";
  budget.textContent = result.filters.budget_label;
  meta.append(budget);

  if (result.filters.search_group_count) {
    const domains = document.createElement("span");
    domains.className = "meta-chip";
    domains.textContent = `${result.filters.search_group_count} nhóm tìm kiếm`;
    meta.append(domains);
  }

  if (result.trace_url) {
    const traceButton = document.createElement("button");
    traceButton.type = "button";
    traceButton.className = "trace-button";
    traceButton.textContent = "Xem trace từng bước";
    traceButton.addEventListener("click", () => openTrace(result.trace_url));
    meta.append(traceButton);
  }

  block.append(meta);
  messages.append(block);
}

function addError(message, traceUrl) {
  const box = document.createElement("div");
  box.className = "error-box";
  box.textContent = message || "Đã có lỗi xảy ra. Bạn thử lại giúp mình nhé.";
  messages.append(box);

  if (traceUrl) {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "trace-button";
    button.textContent = "Xem trace lỗi";
    button.addEventListener("click", () => openTrace(traceUrl));
    box.append(document.createElement("br"), button);
  }
}

function formatTime(timestamp) {
  return new Intl.DateTimeFormat("vi-VN", {
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  }).format(new Date(timestamp));
}

async function openTrace(url) {
  traceDrawer.classList.add("is-open");
  traceDrawer.setAttribute("aria-hidden", "false");
  traceContent.innerHTML = '<p class="trace-empty">Đang tải trace...</p>';
  try {
    const response = await fetch(url);
    const payload = await response.json();
    if (!response.ok) throw new Error(payload.error || "Không tải được trace.");
    traceContent.replaceChildren();
    payload.events.forEach((event) => {
      const row = document.createElement("article");
      row.className = `trace-event is-${event.status}`;

      const dot = document.createElement("span");
      dot.className = "trace-event-dot";

      const topline = document.createElement("div");
      topline.className = "trace-event-topline";
      const step = document.createElement("p");
      step.className = "trace-step";
      step.textContent = `${event.sequence}. ${event.step}`;
      const time = document.createElement("time");
      time.className = "trace-time";
      time.textContent = formatTime(event.timestamp);
      topline.append(step, time);

      row.append(dot, topline);
      if (event.data && Object.keys(event.data).length) {
        const data = document.createElement("pre");
        data.className = "trace-data";
        data.textContent = JSON.stringify(event.data, null, 2);
        row.append(data);
      }
      traceContent.append(row);
    });
  } catch (error) {
    traceContent.innerHTML = "";
    const text = document.createElement("p");
    text.className = "trace-empty";
    text.textContent = error.message;
    traceContent.append(text);
  }
}

function closeTrace() {
  traceDrawer.classList.remove("is-open");
  traceDrawer.setAttribute("aria-hidden", "true");
}

async function sendMessage(text) {
  if (isLoading || !text.trim()) return;
  isLoading = true;
  sendButton.disabled = true;
  document.querySelector("#suggestions")?.remove();
  addUserMessage(text.trim());
  input.value = "";
  resizeInput();
  addLoadingMessage();
  scrollToBottom();

  try {
    const params = new URLSearchParams({ message: text.trim() });
    const response = await fetch(`/api/recommendations?${params.toString()}`, {
      method: "GET",
      headers: { Accept: "application/json" },
      cache: "no-store",
    });
    const payload = await response.json();
    removeLoadingMessage();
    if (!response.ok) {
      addError(payload.error, payload.trace_url);
    } else {
      addResults(payload);
    }
  } catch (error) {
    removeLoadingMessage();
    addError(
      "Không kết nối được với server. Hãy kiểm tra Flask đang chạy ở localhost.",
    );
  } finally {
    isLoading = false;
    sendButton.disabled = false;
    input.focus();
    scrollToBottom();
  }
}

form.addEventListener("submit", (event) => {
  event.preventDefault();
  sendMessage(input.value);
});

input.addEventListener("input", resizeInput);
input.addEventListener("keydown", (event) => {
  if (event.key === "Enter" && !event.shiftKey) {
    event.preventDefault();
    form.requestSubmit();
  }
});

document.querySelectorAll(".suggestion-chip").forEach((button) => {
  button.addEventListener("click", () => sendMessage(button.textContent));
});

clearButton.addEventListener("click", () => {
  if (isLoading) return;
  messages.innerHTML = welcomeMarkup;
  document.querySelectorAll(".suggestion-chip").forEach((button) => {
    button.addEventListener("click", () => sendMessage(button.textContent));
  });
  input.value = "";
  input.focus();
});

document.querySelectorAll("[data-close-trace]").forEach((button) => {
  button.addEventListener("click", closeTrace);
});

document.addEventListener("keydown", (event) => {
  if (event.key === "Escape") closeTrace();
});
