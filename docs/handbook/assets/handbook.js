/* ============================================================================
   Music Library Manager — Handbook navigation + Mermaid runtime.
   Builds the sidebar, prev/next footer, progress bar; boots Mermaid.
   ========================================================================== */

const CHAPTERS = [
  { group: "Orientation" },
  { file: "index.html",              num: "",   title: "Cover & Contents" },
  { file: "ch01-introduction.html",  num: "01", title: "Introduction & Vision" },
  { file: "ch02-history.html",       num: "02", title: "Project History & Evolution" },
  { file: "ch03-features.html",      num: "03", title: "The Complete Feature Catalog" },

  { group: "Architecture" },
  { file: "ch04-architecture.html",  num: "04", title: "System Architecture" },
  { file: "ch05-tech-stack.html",    num: "05", title: "The Technology Stack" },
  { file: "ch06-data-flows.html",    num: "06", title: "Data Flows End-to-End" },

  { group: "The Backend" },
  { file: "ch07-backend.html",       num: "07", title: "Backend Overview (FastAPI)" },
  { file: "ch08-api-reference.html", num: "08", title: "Complete API Reference" },
  { file: "ch09-services.html",      num: "09", title: "Business Logic & Services" },
  { file: "ch10-database.html",      num: "10", title: "The Database Layer" },
  { file: "ch11-analysis.html",      num: "11", title: "The Audio Analysis Engine" },
  { file: "ch12-anlz.html",          num: "12", title: "The ANLZ Binary Format" },
  { file: "ch13-usb-export.html",    num: "13", title: "Pioneer USB Export" },

  { group: "The Frontend" },
  { file: "ch14-frontend.html",      num: "14", title: "Frontend Architecture" },
  { file: "ch15-components.html",    num: "15", title: "Component Reference" },
  { file: "ch16-daw.html",           num: "16", title: "The DAW Editor" },
  { file: "ch17-waveform.html",      num: "17", title: "Waveform & State Management" },

  { group: "Native & Integrations" },
  { file: "ch18-rust-tauri.html",    num: "18", title: "The Rust / Tauri Layer" },
  { file: "ch19-native-audio.html",  num: "19", title: "The Native Audio Engine" },
  { file: "ch20-soundcloud.html",    num: "20", title: "SoundCloud Integration" },

  { group: "Quality & Operations" },
  { file: "ch21-security.html",      num: "21", title: "Security Architecture" },
  { file: "ch22-build-deploy.html",  num: "22", title: "Build, Packaging & Deployment" },
  { file: "ch23-testing.html",       num: "23", title: "Testing & Quality Assurance" },
  { file: "ch24-pipeline.html",      num: "24", title: "The R&D Pipeline" },

  { group: "Forward & Reference" },
  { file: "ch25-roadmap.html",       num: "25", title: "The Future Roadmap" },
  { file: "ch26-dev-guide.html",     num: "26", title: "Developer Guide" },
  { file: "ch27-glossary.html",      num: "27", title: "Glossary of Terms" },
  { file: "ch28-appendices.html",    num: "28", title: "Appendices & Reference" },
];

(function () {
  const path = location.pathname.split("/").pop() || "index.html";
  const pages = CHAPTERS.filter((c) => c.file);
  const idx = pages.findIndex((c) => c.file === path);

  /* ---- sidebar --------------------------------------------------------- */
  const sb = document.getElementById("sidebar");
  if (sb) {
    let html = `
      <div class="sb-brand">
        <a href="index.html">
          <div class="mark"><span class="dot">M</span><span>Music Library Manager</span></div>
          <div class="sub">Comprehensive Handbook</div>
        </a>
      </div>
      <nav class="sb-nav">`;
    for (const c of CHAPTERS) {
      if (c.group) {
        html += `<div class="sb-group-title">${c.group}</div>`;
      } else {
        const active = c.file === path ? " active" : "";
        const numHtml = c.num ? `<span class="ch-num">${c.num}</span>` : `<span class="ch-num">»</span>`;
        html += `<a class="sb-link${active}" href="${c.file}">${numHtml}<span>${c.title}</span></a>`;
      }
    }
    html += `</nav>`;
    sb.innerHTML = html;
  }

  /* ---- mobile topbar title -------------------------------------------- */
  const tbTitle = document.querySelector("#topbar .tb-title");
  if (tbTitle && idx >= 0) tbTitle.textContent = pages[idx].title;

  /* ---- menu toggle ---------------------------------------------------- */
  const toggle = document.getElementById("menu-toggle");
  if (toggle && sb) {
    toggle.addEventListener("click", () => sb.classList.toggle("open"));
    document.addEventListener("click", (e) => {
      if (window.innerWidth <= 860 && sb.classList.contains("open") &&
          !sb.contains(e.target) && e.target !== toggle) {
        sb.classList.remove("open");
      }
    });
  }

  /* ---- prev / next footer --------------------------------------------- */
  const footer = document.getElementById("ch-footer");
  if (footer && idx >= 0) {
    const prev = idx > 0 ? pages[idx - 1] : null;
    const next = idx < pages.length - 1 ? pages[idx + 1] : null;
    footer.innerHTML = `
      ${prev
        ? `<a href="${prev.file}"><div class="dir">‹ Previous</div><div class="ttl">${prev.title}</div></a>`
        : `<a class="disabled"><div class="dir">‹ Previous</div><div class="ttl">—</div></a>`}
      ${next
        ? `<a class="next" href="${next.file}"><div class="dir">Next ›</div><div class="ttl">${next.title}</div></a>`
        : `<a class="next disabled"><div class="dir">Next ›</div><div class="ttl">—</div></a>`}`;
  }

  /* ---- progress bar + back-to-top ------------------------------------- */
  const bar = document.getElementById("progress-bar");
  const toTop = document.getElementById("to-top");
  function onScroll() {
    const h = document.documentElement;
    const scrolled = h.scrollTop / (h.scrollHeight - h.clientHeight || 1);
    if (bar) bar.style.width = Math.min(100, scrolled * 100) + "%";
    if (toTop) toTop.classList.toggle("show", h.scrollTop > 600);
  }
  window.addEventListener("scroll", onScroll, { passive: true });
  onScroll();
  if (toTop) toTop.addEventListener("click", () => window.scrollTo({ top: 0, behavior: "smooth" }));

  /* ---- Mermaid (CDN, graceful offline fallback) ----------------------- */
  const mermaidTheme = {
    startOnLoad: false,
    theme: "base",
    securityLevel: "loose",
    fontFamily: '"DM Sans", system-ui, sans-serif',
    themeVariables: {
      darkMode: true,
      background: "#0d1320",
      primaryColor: "#141c2b",
      primaryTextColor: "#e2e8f0",
      primaryBorderColor: "#e8a42a",
      lineColor: "#64748b",
      secondaryColor: "#1a2336",
      tertiaryColor: "#111827",
      mainBkg: "#141c2b",
      nodeBorder: "#e8a42a",
      clusterBkg: "#0d1320",
      clusterBorder: "#334155",
      titleColor: "#e8a42a",
      edgeLabelBackground: "#0d1320",
      actorBkg: "#141c2b",
      actorBorder: "#e8a42a",
      actorTextColor: "#e2e8f0",
      signalColor: "#94a3b8",
      signalTextColor: "#cbd5e1",
      labelBoxBkgColor: "#141c2b",
      labelBoxBorderColor: "#e8a42a",
      labelTextColor: "#e2e8f0",
      noteBkgColor: "#2a2410",
      noteBorderColor: "#e8a42a",
      noteTextColor: "#e2e8f0",
      pie1: "#e8a42a", pie2: "#3b82f6", pie3: "#34d399", pie4: "#a78bfa",
      pie5: "#f87171", pie6: "#22d3ee", pie7: "#f5c563", pie8: "#818cf8",
      classText: "#e2e8f0",
    },
  };
  const blocks = document.querySelectorAll(".mermaid");
  if (blocks.length) {
    import("https://cdn.jsdelivr.net/npm/mermaid@11/dist/mermaid.esm.min.mjs")
      .then((mod) => {
        const mermaid = mod.default;
        mermaid.initialize(mermaidTheme);
        mermaid.run({ nodes: blocks }).catch((e) => console.warn("[handbook] mermaid render issue", e));
      })
      .catch(() => {
        document.querySelectorAll(".figure").forEach((fig) => {
          const cap = fig.querySelector("figcaption");
          if (cap && !cap.dataset.warned) {
            cap.dataset.warned = "1";
            const w = document.createElement("div");
            w.style.cssText = "color:#f87171;font-size:12px;margin-top:6px";
            w.textContent = "Diagram engine offline — showing diagram source above. Connect to the internet to render.";
            cap.appendChild(w);
          }
        });
      });
  }
})();
