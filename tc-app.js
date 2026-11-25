/* 资费监控站 前端公共库：接口地址 / 登录态 / 请求封装 / 顶栏与刷新按钮 */
window.TC = (function () {
  var API = 'https://socialist-cow-d3glswv91d832ff2d-1252525450.ap-shanghai.app.tcloudbase.com/api';

  var K = { token: 'tc_token', user: 'tc_user', cred: 'tc_cred' };

  function ls(k, v) {
    try {
      if (v === undefined) return localStorage.getItem(k);
      if (v === null) return localStorage.removeItem(k);
      localStorage.setItem(k, v);
    } catch (e) {}
  }
  function ss(k, v) {
    try {
      if (v === undefined) return sessionStorage.getItem(k);
      if (v === null) return sessionStorage.removeItem(k);
      sessionStorage.setItem(k, v);
    } catch (e) {}
  }

  function getToken() {
    return ls(K.token) || ss(K.token) || '';
  }
  function getUser() {
    try {
      return JSON.parse(ls(K.user) || ss(K.user) || 'null');
    } catch (e) {
      return null;
    }
  }
  function saveSession(token, user, remember) {
    if (remember) {
      ls(K.token, token);
      ls(K.user, JSON.stringify(user));
      ss(K.token, null);
      ss(K.user, null);
    } else {
      ss(K.token, token);
      ss(K.user, JSON.stringify(user));
      ls(K.token, null);
      ls(K.user, null);
    }
  }
  function clearSession() {
    ls(K.token, null);
    ls(K.user, null);
    ss(K.token, null);
    ss(K.user, null);
  }

  // 记住密码（本地混淆存储，仅用于回填登录框）
  function saveCred(u, p) {
    try {
      ls(K.cred, btoa(unescape(encodeURIComponent(u + '\u0001' + p))));
    } catch (e) {}
  }
  function loadCred() {
    try {
      var raw = ls(K.cred);
      if (!raw) return null;
      var s = decodeURIComponent(escape(atob(raw)));
      var i = s.indexOf('\u0001');
      if (i < 0) return null;
      return { username: s.slice(0, i), password: s.slice(i + 1) };
    } catch (e) {
      return null;
    }
  }
  function clearCred() {
    ls(K.cred, null);
  }

  async function req(path, opts) {
    opts = opts || {};
    var headers = { 'Content-Type': 'application/json' };
    var t = getToken();
    if (t) headers.Authorization = 'Bearer ' + t;
    var res;
    try {
      res = await fetch(API + path, {
        method: opts.method || 'GET',
        headers: headers,
        body: opts.body ? JSON.stringify(opts.body) : undefined,
      });
    } catch (e) {
      throw { status: 0, message: '网络请求失败，请检查网络后重试' };
    }
    var data = null;
    try {
      data = await res.json();
    } catch (e) {
      data = {};
    }
    if (res.status === 401) {
      clearSession();
      if (!/login\.html/.test(location.pathname)) {
        setTimeout(function () {
          location.replace('login.html');
        }, 400);
      }
      throw { status: 401, message: data.error || '登录已失效' };
    }
    if (!res.ok) throw { status: res.status, message: data.error || '请求失败 (' + res.status + ')' };
    return data;
  }

  function logout() {
    clearSession();
    location.replace('login.html');
  }

  // 页面守卫：无 token 直接跳登录
  function guard() {
    if (!getToken()) {
      location.replace('login.html');
      return false;
    }
    return true;
  }

  var CSS = [
    '.tcbar{position:fixed;right:16px;bottom:16px;z-index:99999;font-family:-apple-system,BlinkMacSystemFont,"Segoe UI","PingFang SC","Microsoft YaHei",sans-serif}',
    '.tcbar .tcfab{display:flex;align-items:center;gap:6px;background:var(--ac,#3f6fd8);color:#fff;border:none;border-radius:999px;padding:10px 16px;font-size:13px;font-weight:600;cursor:pointer;box-shadow:0 8px 24px rgba(63,111,216,.35)}',
    '.tcbar .tcpanel{position:absolute;right:0;bottom:56px;width:236px;background:#fff;color:#1a2230;border:1px solid #e6e9ef;border-radius:14px;box-shadow:0 18px 46px rgba(15,25,40,.18);padding:8px;display:none}',
    '.tcbar.open .tcpanel{display:block}',
    '.tcbar .tcwho{padding:8px 10px 10px;border-bottom:1px solid #eef1f6;margin-bottom:6px;font-size:12px;color:#6b7686}',
    '.tcbar .tcwho b{display:block;color:#1a2230;font-size:13px;margin-bottom:2px}',
    '.tcbar a.tcitem,.tcbar button.tcitem{display:block;width:100%;text-align:left;background:none;border:none;padding:9px 10px;border-radius:9px;font-size:13px;color:#1a2230;cursor:pointer;text-decoration:none;font-family:inherit}',
    '.tcbar .tcitem:hover{background:#f2f5fb}',
    '.tcbar .tcitem:disabled{opacity:.5;cursor:not-allowed;background:none}',
    '.tcbar .tcdot{display:inline-block;width:7px;height:7px;border-radius:50%;background:#0f7a46;margin-right:6px;vertical-align:middle}',
    '.tcbar .tcdot.busy{background:#c98a12;animation:tcpulse 1.1s infinite}',
    '@keyframes tcpulse{0%,100%{opacity:1}50%{opacity:.25}}',
    '@media (prefers-color-scheme:dark){.tcbar .tcpanel{background:#151f2b;color:#dfe6f2;border-color:#26313f}.tcbar .tcwho{color:#8ea0b8;border-color:#222d3a}.tcbar .tcwho b{color:#eaf0fb}.tcbar a.tcitem,.tcbar button.tcitem{color:#dfe6f2}.tcbar .tcitem:hover{background:#1d2836}}',
  ].join('\n');

  function style() {
    if (document.getElementById('tc-bar-css')) return;
    var s = document.createElement('style');
    s.id = 'tc-bar-css';
    s.textContent = CSS;
    document.head.appendChild(s);
  }

  // 挂载右下角工具栏 + 一键刷新
  function mountBar() {
    if (document.querySelector('.tcbar')) return;
    var u = getUser();
    if (!u) return;
    style();
    var el = document.createElement('div');
    el.className = 'tcbar';
    el.innerHTML =
      '<div class="tcpanel">' +
      '<div class="tcwho"><b></b><span></span></div>' +
      '<a class="tcitem" href="push-center.html">我的推送配置</a>' +
      (u.role === 'admin' ? '<a class="tcitem" href="admin.html">账号管理</a>' : '') +
      '<button class="tcitem tcrefresh" type="button"><span class="tcdot"></span><span class="txt">立即刷新</span></button>' +
      '<button class="tcitem tclogout" type="button">退出登录</button>' +
      '</div>' +
      '<button class="tcfab" type="button">我的</button>';
    document.body.appendChild(el);
    el.querySelector('.tcwho b').textContent = u.display_name || u.username;
    el.querySelector('.tcwho span').textContent = u.role === 'admin' ? '管理员' : '普通账号';

    el.querySelector('.tcfab').addEventListener('click', function () {
      el.classList.toggle('open');
    });
    el.querySelector('.tclogout').addEventListener('click', logout);

    var btn = el.querySelector('.tcrefresh');
    var dot = btn.querySelector('.tcdot');
    var txt = btn.querySelector('.txt');
    var busy = false;

    function paint(st) {
      busy = !!st.running;
      dot.className = 'tcdot' + (busy ? ' busy' : '');
      if (busy) {
        txt.textContent = '抓取中…（' + (st.active_run && st.active_run.name ? st.active_run.name : '进行中') + '）';
        btn.disabled = true;
      } else if (st.cooldown_remain > 0) {
        txt.textContent = '冷却中 ' + st.cooldown_remain + 's';
        btn.disabled = true;
      } else {
        txt.textContent = '立即刷新';
        btn.disabled = false;
      }
    }

    async function poll() {
      try {
        var st = await req('/refresh/status');
        paint(st);
      } catch (e) {
        txt.textContent = '状态获取失败';
      }
    }

    btn.addEventListener('click', async function () {
      if (busy) return;
      btn.disabled = true;
      txt.textContent = '正在触发…';
      try {
        await req('/refresh', { method: 'POST' });
        txt.textContent = '已提交，抓取中…';
        setTimeout(poll, 3000);
      } catch (e) {
        txt.textContent = e.message || '触发失败';
        setTimeout(poll, 2500);
      }
    });

    poll();
    setInterval(poll, 20000);
  }

  return {
    API: API,
    getToken: getToken,
    getUser: getUser,
    saveSession: saveSession,
    clearSession: clearSession,
    saveCred: saveCred,
    loadCred: loadCred,
    clearCred: clearCred,
    req: req,
    logout: logout,
    guard: guard,
    mountBar: mountBar,
  };
})();
