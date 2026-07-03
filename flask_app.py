"""
flask_app.py — Prism: Inbox Intelligence
Run: python flask_app.py → http://127.0.0.1:5000
"""

import json, os
from datetime import datetime
from flask import Flask, render_template_string, jsonify, request
from src.drafting import draft_reply
from src.memory_store import initialize_db, get_sender_pattern, confirm_batch_results

app = Flask(__name__)
app.config['SEND_FILE_MAX_AGE_DEFAULT'] = 0

@app.after_request
def no_cache(response):
    response.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate'
    response.headers['Pragma'] = 'no-cache'
    response.headers['Expires'] = '0'
    return response

CHECKPOINT_PATH = "data/triage_results_checkpoint.json"
EMAILS_PATH     = "data/sample_emails.json"
TODO_PATH       = "data/todos.json"
DB_PATH         = "data/memory.db"

CATEGORY_ORDER  = ["time-sensitive","actionable","informational","noise"]
CATEGORY_COLORS = {"time-sensitive":"#E8453C","actionable":"#1A7F5A","informational":"#2B6CB0","noise":"#9B9EAD"}
CATEGORY_BG     = {"time-sensitive":"#FEF2F2","actionable":"#F0FDF4","informational":"#EFF6FF","noise":"#F8F9FF"}
CATEGORY_ICONS  = {"time-sensitive":"⏰","actionable":"✅","informational":"ℹ️","noise":"🔇"}
CATEGORY_LABELS = {"time-sensitive":"Time-sensitive","actionable":"Actionable","informational":"Informational","noise":"Noise"}
REPLY_WORTHY    = {"time-sensitive","actionable"}

HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>Prism — Inbox Intelligence</title>
<style>
*{box-sizing:border-box;margin:0;padding:0}
body{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;background:#F8F9FF;color:#0A0A0F;height:100vh;display:flex;flex-direction:column;overflow:hidden}

/* Name modal */
.modal-overlay{position:fixed;inset:0;background:rgba(0,0,0,0.35);z-index:100;display:flex;align-items:center;justify-content:center}
.modal{background:#fff;border-radius:14px;padding:32px;width:380px;box-shadow:0 20px 60px rgba(0,0,0,0.15)}
.modal-logo{display:flex;align-items:center;gap:10px;margin-bottom:20px}
.modal-title{font-size:18px;font-weight:700;color:#0A0A0F;margin-bottom:6px}
.modal-sub{font-size:13px;color:#9B9EAD;margin-bottom:20px;line-height:1.5}
.modal-input{width:100%;border:0.5px solid #E2E5F0;border-radius:8px;padding:10px 14px;font-size:14px;font-family:inherit;color:#0A0A0F;outline:none;margin-bottom:12px}
.modal-input:focus{border-color:#2B6CB0}
.modal-btn{width:100%;background:#0A0A0F;color:#fff;border:none;border-radius:8px;padding:11px;font-size:14px;font-weight:600;cursor:pointer;font-family:inherit}

/* Header */
.header{background:#fff;border-bottom:0.5px solid #E2E5F0;padding:12px 24px;display:flex;align-items:center;justify-content:space-between;flex-shrink:0}
.logo{display:flex;align-items:center;gap:10px}
.logo-text{font-size:17px;font-weight:700;letter-spacing:-0.5px}
.logo-sub{font-size:11px;color:#9B9EAD}
.header-center{display:flex;align-items:center;gap:8px;background:#F8F9FF;border:0.5px solid #E2E5F0;border-radius:8px;padding:7px 14px;width:300px}
.header-center input{border:none;background:transparent;font-size:13px;color:#3B3E4F;outline:none;width:100%}
.header-center input::placeholder{color:#C4C7D4}
.header-user{font-size:13px;color:#5B5F72;display:flex;align-items:center;gap:6px}
.user-dot{width:28px;height:28px;background:#F2F3FA;border-radius:50%;display:flex;align-items:center;justify-content:center;font-size:12px;font-weight:600;color:#2B6CB0}

/* Layout: sidebar | email-list | detail | todo */
.layout{display:grid;grid-template-columns:190px 300px 1fr 260px;flex:1;overflow:hidden}

/* Sidebar */
.sidebar{background:#fff;border-right:0.5px solid #E2E5F0;display:flex;flex-direction:column;overflow-y:auto}
.sidebar-label{font-size:10px;text-transform:uppercase;letter-spacing:0.8px;color:#C4C7D4;padding:14px 16px 6px;display:block}
.cat-item{padding:9px 16px;display:flex;align-items:center;justify-content:space-between;cursor:pointer;border-right:3px solid transparent;transition:background 0.1s}
.cat-item:hover{background:#F8F9FF}
.cat-item.active{background:#F2F3FA}
.cat-left{display:flex;align-items:center;gap:8px}
.cat-dot{width:8px;height:8px;border-radius:50%;flex-shrink:0}
.cat-name{font-size:13px;color:#3B3E4F}
.cat-count{font-size:12px;font-weight:600}
.divider{height:0.5px;background:#E2E5F0;margin:8px 16px}
.confirm-btn{margin:10px 16px;background:#F8F9FF;border:0.5px solid #E2E5F0;border-radius:8px;padding:8px 12px;font-size:12px;color:#5B5F72;cursor:pointer;text-align:left;font-family:inherit;width:calc(100% - 32px)}
.confirm-btn:hover{background:#F0F1F8}
.confirm-msg{font-size:11px;color:#1A7F5A;padding:0 16px 10px;display:none;line-height:1.4}

/* Email list */
.email-list{border-right:0.5px solid #E2E5F0;overflow-y:auto;background:#F8F9FF}
.list-header{padding:14px 16px 10px;border-bottom:0.5px solid #E2E5F0;background:#fff;position:sticky;top:0;z-index:1}
.list-title{font-size:15px;font-weight:700;color:#0A0A0F}
.list-count{font-size:12px;color:#9B9EAD;margin-top:2px}
.email-card{padding:13px 14px;border-bottom:0.5px solid #E2E5F0;cursor:pointer;background:#fff;display:flex;gap:10px;transition:background 0.1s}
.email-card:hover{background:#F2F3FA}
.email-card.active{background:#EEF0F8;border-right:3px solid #2B6CB0}
.email-bar{width:3px;border-radius:2px;flex-shrink:0;align-self:stretch;min-height:40px}
.email-card-content{flex:1;min-width:0}
.email-subject{font-size:13px;font-weight:600;color:#0A0A0F;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;margin-bottom:2px}
.email-from{font-size:11px;color:#9B9EAD;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;margin-bottom:4px}
.email-snippet{font-size:11px;color:#9B9EAD;line-height:1.4;display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden}
.badge{border-radius:4px;padding:2px 7px;font-size:10px;font-weight:700;white-space:nowrap;flex-shrink:0;align-self:flex-start}
.empty-state{padding:40px 16px;text-align:center;color:#C4C7D4;font-size:13px}

/* Detail */
.detail{overflow-y:auto;padding:24px;background:#F8F9FF;border-right:0.5px solid #E2E5F0}
.detail-empty{display:flex;flex-direction:column;align-items:center;justify-content:center;height:100%;color:#C4C7D4;font-size:14px;gap:10px;text-align:center}
.detail-badge{display:inline-flex;align-items:center;gap:5px;border-radius:6px;padding:4px 12px;font-size:11px;font-weight:700;text-transform:uppercase;margin-bottom:12px}
.detail-subject{font-size:21px;font-weight:700;color:#0A0A0F;margin-bottom:4px;line-height:1.3}
.detail-meta{font-size:13px;color:#9B9EAD;margin-bottom:20px}
.section-label{font-size:10px;text-transform:uppercase;letter-spacing:0.5px;color:#C4C7D4;margin-bottom:6px}
.body-box{background:#fff;border-radius:8px;border:0.5px solid #E2E5F0;padding:14px;font-family:'Courier New',monospace;font-size:13px;color:#3B3E4F;line-height:1.7;white-space:pre-wrap;margin-bottom:14px}
.reasoning-box{border-radius:8px;padding:12px 14px;margin-bottom:14px;border-left:3px solid}
.reasoning-text{font-size:13px;font-style:italic;font-family:Georgia,serif;line-height:1.6}
.memory-box{background:#F5F3FF;border-radius:8px;padding:10px 14px;margin-bottom:14px;border-left:3px solid #7C3AED;font-size:13px;color:#3B3E4F}
.memory-label{font-size:10px;text-transform:uppercase;letter-spacing:0.5px;color:#7C3AED;margin-bottom:3px}

/* Draft */
.draft-section{margin-top:20px;border-top:0.5px solid #E2E5F0;padding-top:18px}
.draft-title{font-size:14px;font-weight:600;color:#0A0A0F;margin-bottom:12px}
.draft-input{width:100%;border:0.5px solid #E2E5F0;border-radius:8px;padding:10px 14px;font-size:13px;font-family:inherit;color:#0A0A0F;background:#fff;outline:none;transition:border-color 0.15s;margin-bottom:10px}
.draft-input:focus{border-color:#2B6CB0}
.btn{border:none;border-radius:8px;padding:9px 16px;font-size:13px;font-weight:600;cursor:pointer;font-family:inherit;transition:opacity 0.15s}
.btn:hover{opacity:0.85}
.btn-primary{background:#0A0A0F;color:#fff}
.btn-success{background:#1A7F5A;color:#fff}
.btn-danger{background:#E8453C;color:#fff}
.btn-sm{padding:6px 12px;font-size:12px}
.draft-result{background:#fff;border-radius:8px;border:0.5px solid #E2E5F0;padding:16px;margin-top:12px;display:none}
.draft-meta{display:flex;gap:8px;margin-bottom:12px;flex-wrap:wrap}
.meta-pill{background:#F8F9FF;border-radius:6px;padding:4px 10px;font-size:12px;color:#5B5F72}
.draft-body-box{background:#F8F9FF;border-radius:8px;padding:14px;font-family:'Courier New',monospace;font-size:13px;color:#3B3E4F;line-height:1.8;white-space:pre-wrap;border:0.5px solid #E2E5F0;margin-bottom:12px}
.draft-actions{display:flex;gap:8px}
.clarify-box{background:#FFFBEB;border:0.5px solid #F59E0B;border-radius:8px;padding:14px;margin-top:12px;display:none}
.suggested-intent{background:#F5F3FF;border:0.5px solid #7C3AED;border-radius:8px;padding:14px;margin-bottom:10px}
.suggested-label{font-size:10px;text-transform:uppercase;letter-spacing:0.5px;color:#7C3AED;margin-bottom:8px;font-weight:600}
.suggested-body{background:#fff;border-radius:6px;padding:12px;font-family:'Courier New',monospace;font-size:12px;color:#3B3E4F;line-height:1.7;white-space:pre-wrap;border:0.5px solid #E2E5F0;margin-bottom:10px}
.suggested-loading{font-size:12px;color:#9B9EAD;margin-bottom:10px;display:block}
.meta-pill{background:#F8F9FF;border-radius:6px;padding:3px 8px;font-size:11px;color:#5B5F72;display:inline-block}
.loading{font-size:13px;color:#9B9EAD;padding:10px 0;display:none}
.spinner{display:inline-block;width:12px;height:12px;border:2px solid #E2E5F0;border-top-color:#2B6CB0;border-radius:50%;animation:spin 0.8s linear infinite;margin-right:6px;vertical-align:middle}
@keyframes spin{to{transform:rotate(360deg)}}

/* Todo panel */
.todo-panel{background:#fff;display:flex;flex-direction:column;overflow:hidden}
.todo-header{background:linear-gradient(135deg,#667eea,#764ba2);padding:14px 16px 12px;flex-shrink:0}
.todo-title{color:#fff;font-size:14px;font-weight:700}
.todo-progress-wrap{background:rgba(255,255,255,0.3);border-radius:4px;height:4px;margin-top:8px}
.todo-progress-fill{background:#fff;border-radius:4px;height:4px;transition:width 0.3s}
.todo-progress-label{color:rgba(255,255,255,0.8);font-size:10px;margin-top:4px}
.todo-input-row{padding:10px 12px;border-bottom:0.5px solid #E2E5F0;display:flex;gap:6px;flex-shrink:0}
.todo-input{flex:1;border:0.5px solid #E2E5F0;border-radius:8px;padding:7px 12px;font-size:12px;font-family:inherit;color:#0A0A0F;background:#F8F9FF;outline:none}
.todo-input:focus{border-color:#764ba2;background:#fff}
.todo-add-btn{background:#764ba2;color:#fff;border:none;border-radius:8px;padding:7px 12px;font-size:12px;cursor:pointer;font-family:inherit;white-space:nowrap}
.todo-filters{display:flex;gap:5px;padding:8px 12px;border-bottom:0.5px solid #E2E5F0;flex-shrink:0}
.todo-chip{background:#F8F9FF;border:0.5px solid #E2E5F0;border-radius:20px;padding:3px 10px;font-size:10px;color:#5B5F72;cursor:pointer;font-family:inherit}
.todo-chip.active{background:#764ba2;color:#fff;border-color:#764ba2}
.todo-list{flex:1;overflow-y:auto;padding:4px 0}
.todo-item{padding:9px 12px;display:flex;align-items:center;gap:8px;border-bottom:0.5px solid #F2F3FA;transition:background 0.1s}
.todo-item:hover{background:#F8F9FF}
.todo-item.done .todo-text{text-decoration:line-through;color:#C4C7D4}
.todo-priority{width:3px;border-radius:2px;align-self:stretch;min-height:28px;flex-shrink:0}
.todo-check{width:14px;height:14px;border:1.5px solid #E2E5F0;border-radius:3px;cursor:pointer;flex-shrink:0;display:flex;align-items:center;justify-content:center;transition:all 0.15s}
.todo-check.checked{background:#1A7F5A;border-color:#1A7F5A}
.todo-content{flex:1;min-width:0}
.todo-text{font-size:12px;color:#3B3E4F;line-height:1.4}
.todo-source{font-size:10px;color:#C4C7D4;margin-top:1px}
.todo-delete{font-size:13px;color:#E2E5F0;cursor:pointer;flex-shrink:0;opacity:0;transition:opacity 0.15s}
.todo-item:hover .todo-delete{opacity:1}
.todo-empty{padding:28px 16px;text-align:center;color:#C4C7D4;font-size:12px;line-height:1.6}
.todo-footer{padding:8px 12px;border-top:0.5px solid #E2E5F0;display:flex;justify-content:space-between;align-items:center;flex-shrink:0}
.todo-stats{font-size:11px;color:#9B9EAD}
.todo-clear-btn{font-size:11px;color:#E8453C;background:none;border:none;cursor:pointer;font-family:inherit}
</style>
</head>
<body>

<!-- Name modal -->
<div class="modal-overlay" id="nameModal">
  <div class="modal">
    <div class="modal-logo">
      <svg width="48" height="48" viewBox="0 0 32 32" fill="none">
        <polygon points="16,4 28,26 4,26" fill="none" stroke="#0A0A0F" stroke-width="1.5" stroke-linejoin="round"/>
        <line x1="16" y1="4" x2="16" y2="26" stroke="#E8453C" stroke-width="1.2" opacity="0.7"/>
        <line x1="16" y1="4" x2="9" y2="26" stroke="#1A7F5A" stroke-width="1.2" opacity="0.7"/>
        <line x1="16" y1="4" x2="23" y2="26" stroke="#2B6CB0" stroke-width="1.2" opacity="0.7"/>
      </svg>
      <div style="font-size:17px;font-weight:700;letter-spacing:-0.5px;margin-top:8px;">Prism</div>
    </div>
    <div class="modal-title">Welcome to Prism</div>
    <div class="modal-sub">Your AI-powered inbox agent. Enter your name once — it'll be used in all draft sign-offs.</div>
    <input class="modal-input" id="modalNameInput" placeholder="Your name" onkeydown="if(event.key==='Enter')startApp()">
    <button class="modal-btn" onclick="startApp()">Get started →</button>
  </div>
</div>

<!-- Header -->
<div class="header">
  <div class="logo">
    <svg width="28" height="28" viewBox="0 0 32 32" fill="none">
      <polygon points="16,4 28,26 4,26" fill="none" stroke="#0A0A0F" stroke-width="1.5" stroke-linejoin="round"/>
      <line x1="16" y1="4" x2="16" y2="26" stroke="#E8453C" stroke-width="1.2" opacity="0.7"/>
      <line x1="16" y1="4" x2="9" y2="26" stroke="#1A7F5A" stroke-width="1.2" opacity="0.7"/>
      <line x1="16" y1="4" x2="23" y2="26" stroke="#2B6CB0" stroke-width="1.2" opacity="0.7"/>
    </svg>
    <div>
      <div class="logo-text">Prism</div>
      <div class="logo-sub">inbox intelligence</div>
    </div>
  </div>
  <div class="header-center">
    <svg width="14" height="14" fill="none" stroke="#C4C7D4" stroke-width="2" viewBox="0 0 24 24"><circle cx="11" cy="11" r="8"/><path d="m21 21-4.35-4.35"/></svg>
    <input type="text" id="searchInput" placeholder="Search by sender or subject..." oninput="filterEmails()">
  </div>
  <div class="header-user">
    <div class="user-dot" id="userInitial">?</div>
    <span id="userName" style="font-size:13px;color:#5B5F72;"></span>
  </div>
</div>

<!-- Layout -->
<div class="layout">

  <!-- Sidebar -->
  <div class="sidebar">
    <span class="sidebar-label">Categories</span>
    <div id="categoryList"></div>
    <div class="divider"></div>
  </div>

  <!-- Email list -->
  <div class="email-list">
    <div class="list-header">
      <div class="list-title" id="listTitle">Time-sensitive</div>
      <div class="list-count" id="listCount">Loading...</div>
    </div>
    <div id="emailList"></div>
  </div>

  <!-- Detail -->
  <div class="detail" id="detailPanel">
    <div class="detail-empty">
      <svg width="44" height="44" viewBox="0 0 32 32" fill="none">
        <polygon points="16,4 28,26 4,26" fill="none" stroke="#C4C7D4" stroke-width="1.5" stroke-linejoin="round"/>
        <line x1="16" y1="4" x2="16" y2="26" stroke="#E8453C" stroke-width="1" opacity="0.3"/>
        <line x1="16" y1="4" x2="9" y2="26" stroke="#1A7F5A" stroke-width="1" opacity="0.3"/>
        <line x1="16" y1="4" x2="23" y2="26" stroke="#2B6CB0" stroke-width="1" opacity="0.3"/>
      </svg>
      <div>Click an email to view it</div>
      <div style="font-size:12px;color:#E2E5F0;">Details, AI reasoning, and drafting appear here</div>
    </div>
  </div>

  <!-- Todo panel -->
  <div class="todo-panel">
    <div class="todo-header">
      <div class="todo-title">To Do List</div>
      <div class="todo-progress-wrap"><div class="todo-progress-fill" id="todoProgress" style="width:0%"></div></div>
      <div class="todo-progress-label" id="todoProgressLabel">0 of 0 done</div>
    </div>
    <div class="todo-input-row">
      <input class="todo-input" id="todoInput" placeholder="Add a task..." onkeydown="if(event.key==='Enter')addTodo()">
      <button class="todo-add-btn" onclick="addTodo()">Add</button>
    </div>
    <div class="todo-filters">
      <button class="todo-chip active" id="filter-all" onclick="setFilter('all')">All</button>
      <button class="todo-chip" id="filter-pending" onclick="setFilter('pending')">Pending</button>
      <button class="todo-chip" id="filter-done" onclick="setFilter('done')">Done</button>
    </div>
    <div class="todo-list" id="todoList"></div>
    <div class="todo-footer">
      <span class="todo-stats" id="todoStats">0 tasks</span>
      <button class="todo-clear-btn" onclick="clearDone()">Clear done</button>
    </div>
  </div>

</div>

<script>
const COLORS  = {"time-sensitive":"#E8453C","actionable":"#1A7F5A","informational":"#2B6CB0","noise":"#9B9EAD"};
const BGS     = {"time-sensitive":"#FEF2F2","actionable":"#F0FDF4","informational":"#EFF6FF","noise":"#F8F9FF"};
const ICONS   = {"time-sensitive":"⏰","actionable":"✅","informational":"ℹ️","noise":"🔇"};
const LABELS  = {"time-sensitive":"Time-sensitive","actionable":"Actionable","informational":"Informational","noise":"Noise"};
const CATS    = ["time-sensitive","actionable","informational","noise"];
const REPLY_WORTHY = ["time-sensitive","actionable"];

let allData = {results:{}, emails:{}};
let activeCategory = "time-sensitive";
let activeEmailId = null;
let userName = "";
let todos = JSON.parse(localStorage.getItem('prism_todos') || '[]');

// ── Name modal ──────────────────────────────────────────────────────────────
function startApp() {
  const n = document.getElementById('modalNameInput').value.trim();
  userName = n || "User";
  document.getElementById('nameModal').style.display = 'none';
  document.getElementById('userInitial').textContent = userName[0].toUpperCase();
  document.getElementById('userName').textContent = userName;
  loadData();
}

// ── Data ────────────────────────────────────────────────────────────────────
async function loadData() {
  const res = await fetch('/api/data');
  allData = await res.json();
  renderSidebar();
  renderEmailList();
  renderTodos();
}

// ── Sidebar ─────────────────────────────────────────────────────────────────
function renderSidebar() {
  const counts = {};
  CATS.forEach(c => counts[c] = 0);
  Object.values(allData.results).forEach(r => { if(counts[r.category]!==undefined) counts[r.category]++; });

  document.getElementById('categoryList').innerHTML = CATS.map(cat => {
    const color = COLORS[cat];
    const active = cat === activeCategory;
    return `<div class="cat-item ${active?'active':''}" onclick="switchCategory('${cat}')"
      style="${active?'border-right-color:'+color+';':''}">
      <div class="cat-left">
        <div class="cat-dot" style="background:${color}"></div>
        <span class="cat-name">${LABELS[cat]}</span>
      </div>
      <span class="cat-count" style="color:${color}">${counts[cat]}</span>
    </div>`;
  }).join('');
}

// ── Email list ───────────────────────────────────────────────────────────────
function renderEmailList() {
  const q = document.getElementById('searchInput').value.toLowerCase();
  let group = Object.values(allData.results).filter(r => r.category === activeCategory);
  if (q) group = group.filter(r => (r.from||'').toLowerCase().includes(q) || (r.subject||'').toLowerCase().includes(q));

  document.getElementById('listTitle').textContent = LABELS[activeCategory];
  document.getElementById('listCount').textContent = group.length + ' emails';

  const color = COLORS[activeCategory];
  const bg = BGS[activeCategory];
  const icon = ICONS[activeCategory];
  const label = LABELS[activeCategory].toUpperCase();

  if (!group.length) {
    document.getElementById('emailList').innerHTML = '<div class="empty-state">No emails found.</div>';
    return;
  }

  document.getElementById('emailList').innerHTML = group.map(r => {
    const email = allData.emails[r.email_id] || {};
    const active = r.email_id === activeEmailId ? 'active' : '';
    return `<div class="email-card ${active}" onclick="openEmail('${r.email_id}')">
      <div class="email-bar" style="background:${color}"></div>
      <div class="email-card-content">
        <div style="display:flex;align-items:flex-start;justify-content:space-between;gap:6px;margin-bottom:2px;">
          <div class="email-subject">${r.subject||''}</div>
          <div class="badge" style="background:${bg};color:${color}">${icon}</div>
        </div>
        <div class="email-from">${r.from||''}</div>
        <div class="email-snippet">${(email.body||'').substring(0,80)}...</div>
      </div>
    </div>`;
  }).join('');
}

function switchCategory(cat) {
  activeCategory = cat;
  activeEmailId = null;
  renderSidebar();
  renderEmailList();
  document.getElementById('detailPanel').innerHTML = `
    <div class="detail-empty">
      <svg width="44" height="44" viewBox="0 0 32 32" fill="none">
        <polygon points="16,4 28,26 4,26" fill="none" stroke="#C4C7D4" stroke-width="1.5" stroke-linejoin="round"/>
      </svg>
      <div>Click an email to view it</div>
    </div>`;
}

function filterEmails() { renderEmailList(); }

// ── Email detail ─────────────────────────────────────────────────────────────
async function openEmail(emailId) {
  activeEmailId = emailId;
  renderEmailList();

  const r = allData.results[emailId];
  const email = allData.emails[emailId] || {};
  if (!r) return;

  const color = COLORS[r.category];
  const bg = BGS[r.category];
  const icon = ICONS[r.category];
  const label = LABELS[r.category];
  const canDraft = REPLY_WORTHY.includes(r.category);

  const memRes = await fetch(`/api/memory/${encodeURIComponent(r.from||'')}`);
  const mem = await memRes.json();

  const memHtml = mem.known ? `
    <div class="memory-box">
      <div class="memory-label">Sender memory</div>
      <strong>${r.from}</strong> is ${mem.most_common_category || mem.pattern.split(' ')[0]} — ${mem.sample_size} past emails
    </div>` : '';

  const parseHtml = r.parse_error ? `
    <div style="background:#FEF2F2;border:0.5px solid #E8453C;border-radius:8px;padding:12px;margin-bottom:14px;color:#E8453C;font-size:13px;">
      ⚠️ Flagged for manual review — AI response was incomplete.
    </div>` : '';

  const draftHtml = canDraft ? `
    <div class="draft-section">
      <div class="draft-title">Reply</div>
      <div class="suggested-loading" id="suggestedLoading">
        <span class="spinner"></span> Generating suggested reply...
      </div>
      <div class="suggested-intent" id="suggestedIntent" style="display:none;">
        <div class="suggested-label">💡 Suggested reply</div>
        <div class="suggested-meta" id="suggestedMeta"></div>
        <div class="suggested-body" id="suggestedBody"></div>
        <div style="font-size:12px;color:#9B9EAD;margin-bottom:10px;">This is a suggested reply. Review carefully before approving.</div>
        <div style="display:flex;gap:8px;margin-bottom:14px;">
          <button class="btn btn-success" onclick="approveSuggested('${emailId}')">✅ Approve & send (simulated)</button>
          <button class="btn btn-danger btn-sm" onclick="rejectSuggested()">✗ Not right</button>
        </div>
      </div>
      <div id="customDraftSection" style="display:none;">
        <div style="font-size:12px;color:#9B9EAD;margin-bottom:8px;">Write your own intent instead:</div>
        <textarea class="draft-input" id="intentInput" rows="2"
          placeholder="What do you want to say? e.g. 'confirm I'll send the form by Sunday morning'"></textarea>
        <button class="btn btn-primary" onclick="generateDraft('${emailId}')">✍️ Generate draft</button>
        <div class="loading" id="draftLoading"><span class="spinner"></span>Drafting reply — this takes a few seconds...</div>
        <div class="clarify-box" id="draftClarify">
          <div style="font-size:13px;font-weight:600;color:#B45309;margin-bottom:4px;">⚠️ Intent unclear — please clarify</div>
          <div style="font-size:13px;color:#78350F;" id="clarifyText"></div>
        </div>
        <div class="draft-result" id="draftResult">
          <div class="draft-meta" id="draftMeta"></div>
          <div class="section-label">Subject</div>
          <div style="font-size:15px;font-weight:600;color:#0A0A0F;margin-bottom:14px;" id="draftSubject"></div>
          <div class="draft-body-box" id="draftBody"></div>
          <div style="font-size:12px;color:#9B9EAD;margin-bottom:12px;">Review carefully. No email will be sent without your explicit approval.</div>
          <div class="draft-actions">
            <button class="btn btn-success" onclick="approveDraft('${emailId}')">✅ Approve & send (simulated)</button>
            <button class="btn btn-danger btn-sm" onclick="rejectDraft()">❌ Reject</button>
          </div>
        </div>
      </div>
      <div class="send-status" id="sendStatus"></div>
    </div>` : `
    <div style="margin-top:20px;padding-top:16px;border-top:0.5px solid #E2E5F0;font-size:13px;color:#9B9EAD;">
      This email is ${label.toLowerCase()} — no reply needed.
      <button class="btn btn-sm" style="background:#F8F9FF;color:#5B5F72;border:0.5px solid #E2E5F0;margin-left:10px;"
        onclick="addTodoFromEmail('${(r.subject||'').replace(/'/g,"\\'")}')">+ Add to task list</button>
    </div>`;

  document.getElementById('detailPanel').innerHTML = `
    <div>
      <div class="detail-badge" style="background:${bg};color:${color}">${icon} ${label}</div>
      <div class="detail-subject">${r.subject||''}</div>
      <div class="detail-meta">From: ${r.from||''} · ${(email.date||'').substring(0,10)} · Confidence: ${r.confidence||'high'}</div>
      <div class="section-label">Email content</div>
      <div class="body-box">${(email.body||'').replace(/</g,'&lt;')}</div>
      <div class="section-label">AI reasoning</div>
      <div class="reasoning-box" style="background:${bg};border-left-color:${color}">
        <div class="reasoning-text" style="color:${color==='#9B9EAD'?'#5B5F72':color}">"${r.reasoning||''}"</div>
      </div>
      ${memHtml}${parseHtml}${draftHtml}
    </div>`;

  // Auto-fetch suggested reply for actionable/time-sensitive emails
  if (canDraft) {
    fetchSuggestedReply(emailId);
  }
}

let currentSuggestedDraft = null;

async function fetchSuggestedReply(emailId) {
  const res = await fetch('/api/suggest', {
    method: 'POST',
    headers: {'Content-Type':'application/json'},
    body: JSON.stringify({email_id: emailId, name: userName, category: activeCategory})
  });
  const draft = await res.json();

  document.getElementById('suggestedLoading').style.display = 'none';

  if (draft.error || draft.needs_clarification) {
    document.getElementById('customDraftSection').style.display = 'block';
    return;
  }

  currentSuggestedDraft = draft;
  const color = COLORS[activeCategory];

  document.getElementById('suggestedMeta').innerHTML = `
    <div style="display:flex;gap:8px;margin-bottom:8px;flex-wrap:wrap;">
      <div class="meta-pill">To: <strong>${draft.to||''}</strong></div>
      <div class="meta-pill">Tone: <strong style="color:${color}">${draft.tone_detected||''}</strong></div>
      <div class="meta-pill">Subject: <strong>${draft.subject||''}</strong></div>
    </div>`;
  document.getElementById('suggestedBody').textContent = draft.body || '';
  document.getElementById('suggestedIntent').style.display = 'block';
}

function rejectSuggested() {
  document.getElementById('suggestedIntent').style.display = 'none';
  document.getElementById('customDraftSection').style.display = 'block';
  currentSuggestedDraft = null;
}

async function approveSuggested(emailId) {
  if (!currentSuggestedDraft) return;
  const res = await fetch('/api/send_draft', {
    method: 'POST',
    headers: {'Content-Type':'application/json'},
    body: JSON.stringify({
      email_id: emailId,
      draft: currentSuggestedDraft,
      category: activeCategory
    })
  });
  const result = await res.json();
  document.getElementById('suggestedIntent').style.display = 'none';
  const s = document.getElementById('sendStatus');
  s.innerHTML = `✓ Reply logged (simulated — no real email sent)<br><span style="font-size:12px;color:#9B9EAD;">To: ${result.to} · Subject: ${result.subject}</span>`;
  s.style.cssText = 'display:block;background:#F0FDF4;color:#1A7F5A;margin-top:10px;font-size:13px;border-radius:8px;padding:10px 14px;';
}

// ── Draft ────────────────────────────────────────────────────────────────────
async function generateDraft(emailId) {
  const intent = document.getElementById('intentInput').value.trim();
  if (!intent) { alert('Please enter your intent first.'); return; }

  document.getElementById('draftResult').style.display = 'none';
  document.getElementById('draftClarify').style.display = 'none';
  document.getElementById('sendStatus').style.display = 'none';
  document.getElementById('draftLoading').style.display = 'block';

  const res = await fetch('/api/draft', {
    method:'POST', headers:{'Content-Type':'application/json'},
    body: JSON.stringify({email_id:emailId, intent, name:userName, category:activeCategory})
  });
  const draft = await res.json();
  document.getElementById('draftLoading').style.display = 'none';

  if (draft.needs_clarification) {
    document.getElementById('clarifyText').textContent = draft.question;
    document.getElementById('draftClarify').style.display = 'block';
    return;
  }

  const color = COLORS[activeCategory];
  document.getElementById('draftMeta').innerHTML = `
    <div class="meta-pill">To: <strong>${draft.to||''}</strong></div>
    <div class="meta-pill">Tone: <strong style="color:${color}">${draft.tone_detected||''}</strong></div>`;
  document.getElementById('draftSubject').textContent = draft.subject||'';
  document.getElementById('draftBody').textContent = draft.body||'';
  document.getElementById('draftResult').style.display = 'block';
}

function rejectDraft() {
  document.getElementById('draftResult').style.display = 'none';
  const s = document.getElementById('sendStatus');
  s.textContent = 'Draft rejected. Nothing sent.';
  s.style.cssText = 'display:block;background:#FEF2F2;color:#E8453C;';
}

async function approveDraft(emailId) {
  const intent = document.getElementById('intentInput').value.trim();
  const res = await fetch('/api/send', {
    method:'POST', headers:{'Content-Type':'application/json'},
    body: JSON.stringify({email_id:emailId, intent, name:userName, category:activeCategory})
  });
  const result = await res.json();
  document.getElementById('draftResult').style.display = 'none';
  const s = document.getElementById('sendStatus');
  s.innerHTML = `✓ Reply logged (simulated — no real email sent)<br><span style="font-size:12px;color:#9B9EAD;">To: ${result.to} · Subject: ${result.subject}</span>`;
  s.style.cssText = 'display:block;background:#F0FDF4;color:#1A7F5A;';
}

// ── Todo ─────────────────────────────────────────────────────────────────────
let todoFilter = 'all';

function setFilter(f) {
  todoFilter = f;
  ['all','pending','done'].forEach(x => {
    document.getElementById('filter-'+x).classList.toggle('active', x === f);
  });
  renderTodos();
}

function saveTodos() { localStorage.setItem('prism_todos', JSON.stringify(todos)); }

function addTodo() {
  const input = document.getElementById('todoInput');
  const text = input.value.trim();
  if (!text) return;
  todos.unshift({id: Date.now(), text, done: false, source: ''});
  input.value = '';
  saveTodos();
  renderTodos();
}

function addTodoFromEmail(subject) {
  todos.unshift({id: Date.now(), text: `Action: ${subject}`, done: false, source: 'from email'});
  saveTodos();
  renderTodos();
  document.getElementById('todoInput').focus();
}

function addTodoItem(text, source) {
  todos.unshift({id: Date.now(), text, done: false, source});
  saveTodos();
  renderTodos();
}

function toggleTodo(id) {
  const t = todos.find(t => t.id === id);
  if (t) { t.done = !t.done; saveTodos(); renderTodos(); }
}

function deleteTodo(id) {
  todos = todos.filter(t => t.id !== id);
  saveTodos();
  renderTodos();
}

function clearDone() {
  todos = todos.filter(t => !t.done);
  saveTodos();
  renderTodos();
}

function renderTodos() {
  const total = todos.length;
  const done = todos.filter(t => t.done).length;
  const pct = total > 0 ? Math.round((done/total)*100) : 0;

  document.getElementById('todoStats').textContent = `${total - done} remaining · ${done} done`;
  document.getElementById('todoProgress').style.width = pct + '%';
  document.getElementById('todoProgressLabel').textContent = `${done} of ${total} done`;

  let filtered = todos;
  if (todoFilter === 'pending') filtered = todos.filter(t => !t.done);
  if (todoFilter === 'done') filtered = todos.filter(t => t.done);

  if (!filtered.length) {
    document.getElementById('todoList').innerHTML = `
      <div class="todo-empty">
        ${todoFilter === 'done' ? 'No completed tasks yet.' : 'No tasks yet.<br>Add tasks as you review emails.'}
      </div>`;
    return;
  }

  const PRIORITY_COLORS = ['#E8453C','#F59E0B','#1A7F5A','#2B6CB0','#9B9EAD'];

  document.getElementById('todoList').innerHTML = filtered.map((t, i) => {
    const pColor = t.done ? '#E2E5F0' : PRIORITY_COLORS[i % PRIORITY_COLORS.length];
    return `
    <div class="todo-item ${t.done?'done':''}">
      <div class="todo-priority" style="background:${pColor}"></div>
      <div class="todo-check ${t.done?'checked':''}" onclick="toggleTodo(${t.id})">
        ${t.done ? '<svg width="9" height="9" viewBox="0 0 10 10" fill="none"><path d="M2 5l2.5 2.5L8 3" stroke="#fff" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/></svg>' : ''}
      </div>
      <div class="todo-content">
        <div class="todo-text">${t.text}</div>
        ${t.source ? `<div class="todo-source">${t.source}</div>` : ''}
      </div>
      <div class="todo-delete" onclick="deleteTodo(${t.id})">×</div>
    </div>`}).join('');
}

// ── Memory confirm ───────────────────────────────────────────────────────────
async function confirmMemory() {
  const res = await fetch('/api/confirm', {method:'POST'});
  const result = await res.json();
  const msg = document.getElementById('confirmMsg');
  msg.textContent = result.message;
  msg.style.display = 'block';
  setTimeout(() => msg.style.display = 'none', 4000);
}
</script>
</body>
</html>"""


def get_data():
    results, emails = {}, {}
    if os.path.exists(CHECKPOINT_PATH):
        with open(CHECKPOINT_PATH) as f:
            for r in json.load(f):
                if not r.get("mock"):
                    results[r["email_id"]] = r
    if os.path.exists(EMAILS_PATH):
        with open(EMAILS_PATH) as f:
            for e in json.load(f):
                emails[e["id"]] = e
    return results, emails


@app.route("/")
def index():
    return render_template_string(HTML)


@app.route("/api/data")
def api_data():
    results, emails = get_data()
    return jsonify({"results": results, "emails": emails})


@app.route("/api/memory/<path:sender>")
def api_memory(sender):
    initialize_db(DB_PATH)
    pattern = get_sender_pattern(sender, DB_PATH)
    return jsonify(pattern)


@app.route("/api/draft", methods=["POST"])
def api_draft():
    data = request.json
    results, emails = get_data()
    result = results.get(data["email_id"])
    email = emails.get(data["email_id"], {})
    if not result:
        return jsonify({"error": "not found"}), 404
    draft = draft_reply(email, result, data.get("intent",""), user_name=data.get("name","Your Name"))
    draft["to"] = email.get("from","")
    return jsonify(draft)


@app.route("/api/send", methods=["POST"])
def api_send():
    data = request.json
    results, emails = get_data()
    result = results.get(data["email_id"])
    email = emails.get(data["email_id"], {})
    if not result:
        return jsonify({"error": "not found"}), 404
    draft = draft_reply(email, result, data.get("intent",""), user_name=data.get("name","Your Name"))
    log_entry = {"sent_at": datetime.now().isoformat(), "to": email.get("from",""), "original_subject": email.get("subject",""), "reply_subject": draft.get("subject",""), "reply_body": draft.get("body",""), "tone_detected": draft.get("tone_detected",""), "user_intent": data.get("intent",""), "simulated": True}
    log_path = "data/sent_log.json"
    existing = []
    if os.path.exists(log_path):
        with open(log_path) as f:
            existing = json.load(f)
    existing.append(log_entry)
    with open(log_path, "w") as f:
        json.dump(existing, f, indent=2)
    return jsonify({"to": email.get("from",""), "subject": draft.get("subject","")})


@app.route("/api/suggest", methods=["POST"])
def api_suggest():
    """Auto-generates a suggested reply when an email is opened."""
    data = request.json
    results, emails = get_data()
    result = results.get(data["email_id"])
    email = emails.get(data["email_id"], {})
    if not result:
        return jsonify({"error": "not found"}), 404

    # Generate a sensible default intent based on the email category
    category = data.get("category", result.get("category", "actionable"))
    default_intents = {
        "actionable": "acknowledge the request and provide a helpful response",
        "time-sensitive": "acknowledge the deadline and confirm you will address it promptly",
    }
    intent = default_intents.get(category, "acknowledge this email with an appropriate response")

    draft = draft_reply(email, result, intent, user_name=data.get("name", "Your Name"))
    draft["to"] = email.get("from", "")
    return jsonify(draft)


@app.route("/api/send_draft", methods=["POST"])
def api_send_draft():
    """Logs an already-generated draft as a simulated send."""
    data = request.json
    results, emails = get_data()
    email = emails.get(data["email_id"], {})
    draft = data.get("draft", {})

    log_entry = {
        "sent_at": datetime.now().isoformat(),
        "to": email.get("from", ""),
        "original_subject": email.get("subject", ""),
        "reply_subject": draft.get("subject", ""),
        "reply_body": draft.get("body", ""),
        "tone_detected": draft.get("tone_detected", ""),
        "user_intent": "suggested reply (auto-approved)",
        "simulated": True,
    }
    log_path = "data/sent_log.json"
    existing = []
    if os.path.exists(log_path):
        with open(log_path) as f:
            existing = json.load(f)
    existing.append(log_entry)
    with open(log_path, "w") as f:
        json.dump(existing, f, indent=2)

    return jsonify({"to": email.get("from", ""), "subject": draft.get("subject", "")})
    results, _ = get_data()
    initialize_db(DB_PATH)
    live = list(results.values())
    result = confirm_batch_results(live, DB_PATH)
    return jsonify({"message": f"✓ {result['confirmed']} results confirmed. ({result['skipped_parse_errors']} parse errors skipped.)"})


if __name__ == "__main__":
    initialize_db(DB_PATH)
    # Auto-build sender memory from checkpoint if memory.db is empty
    # This ensures the live deployment (Render) has memory working on first load
    try:
        from src.memory_store import get_all_sender_patterns
        existing = get_all_sender_patterns(DB_PATH)
        if not existing and os.path.exists(CHECKPOINT_PATH):
            print("Building sender memory from checkpoint...")
            results, _ = get_data()
            live = [r for r in results.values() if not r.get("mock")]
            confirm_batch_results(live, DB_PATH)
            print(f"Memory built: {len(get_all_sender_patterns(DB_PATH))} senders learned.")
    except Exception as e:
        print(f"Memory init skipped: {e}")
    print("\n🔷 Prism is running → http://127.0.0.1:5000\n")
    port = int(os.environ.get("PORT", 5000))
    app.run(debug=False, host="0.0.0.0", port=port)
