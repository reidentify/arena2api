/**
 * Arena2API - Injector (MAIN world)
 * 
 * 在页面主世界中运行，可以直接访问：
 * - window.grecaptcha.enterprise
 * - window.__next_f (Next.js 数据)
 * - 页面的所有全局变量
 * 
 * 通过 window.postMessage 与 content.js 通信
 */
(function() {
  'use strict';

  var SITEKEY = '6Led_uYrAAAAAKjxDIF58fgFtX3t8loNAK85bW9I';
  var TAG = '[Arena2API]';

  // ========== 提取模型列表 ==========
  function extractModels() {
    try {
      // 方法1：从 __NEXT_DATA__ 提取
      if (window.__NEXT_DATA__) {
        var props = window.__NEXT_DATA__.props;
        if (props && props.pageProps && props.pageProps.initialModels) {
          return props.pageProps.initialModels;
        }
      }

      // 方法2：从 self.__next_f 提取
      if (window.__next_f) {
        for (var i = 0; i < window.__next_f.length; i++) {
          var entry = window.__next_f[i];
          if (!entry || !entry[1]) continue;
          var str = typeof entry[1] === 'string' ? entry[1] : '';
          if (str.indexOf('initialModels') >= 0) {
            // 找到 JSON 部分
            var jsonStart = str.indexOf('{"initialModels"');
            if (jsonStart < 0) jsonStart = str.indexOf('"initialModels"');
            if (jsonStart >= 0) {
              // 向前找到包含它的对象开始
              var braceStart = str.lastIndexOf('{', jsonStart);
              if (braceStart >= 0) {
                // 尝试解析
                var depth = 0;
                for (var j = braceStart; j < str.length; j++) {
                  if (str[j] === '{') depth++;
                  else if (str[j] === '}') depth--;
                  if (depth === 0) {
                    try {
                      var obj = JSON.parse(str.substring(braceStart, j + 1));
                      if (obj.initialModels) return obj.initialModels;
                    } catch(e) {}
                    break;
                  }
                }
              }
            }
          }
        }
      }

      // 方法3：从 HTML script 标签提取
      var scripts = document.querySelectorAll('script');
      for (var k = 0; k < scripts.length; k++) {
        var text = scripts[k].textContent || '';
        if (text.indexOf('initialModels') >= 0 && text.indexOf('self.__next_f.push') >= 0) {
          var match = text.match(/initialModels":\s*(\[[\s\S]*?\])\s*,\s*"/);
          if (match) {
            try {
              return JSON.parse(match[1]);
            } catch(e) {}
          }
        }
      }
    } catch(e) {
      console.error(TAG, 'extractModels error:', e);
    }
    return null;
  }

  // ========== 提取 Next.js server action hashes ==========
  function extractNextActions() {
    // 这些 hash 用于 Next.js server actions（如 generateUploadUrl 等）
    // 暂时不需要，后续如果支持图片上传再添加
    return {};
  }

  // ========== reCAPTCHA token 获取 ==========
  function getRecaptchaToken(action) {
    return new Promise(function(resolve, reject) {
      var g = window.grecaptcha && window.grecaptcha.enterprise
        ? window.grecaptcha.enterprise
        : window.grecaptcha;

      if (!g || typeof g.execute !== 'function') {
        reject(new Error('grecaptcha not available'));
        return;
      }

      g.ready(function() {
        g.execute(SITEKEY, { action: action || 'chat_submit' })
          .then(resolve)
          .catch(reject);
      });
    });
  }

  // ========== 提取 cookies ==========
  function extractCookies() {
    var cookies = {};
    try {
      var cookieStr = document.cookie;
      if (cookieStr) {
        cookieStr.split(';').forEach(function(pair) {
          var parts = pair.trim().split('=');
          if (parts.length >= 2) {
            cookies[parts[0]] = parts.slice(1).join('=');
          }
        });
      }
    } catch(e) {
      console.error(TAG, 'extractCookies error:', e);
    }
    return cookies;
  }

  // ========== 消息处理 ==========
  window.addEventListener('message', function(event) {
    if (event.source !== window) return;
    if (!event.data || event.data.from !== 'arena2api-content') return;

    var msg = event.data;
    var rid = msg.rid;

    switch (msg.type) {
      case 'GET_TOKEN':
        getRecaptchaToken(msg.action).then(function(token) {
          window.postMessage({
            from: 'arena2api-injector',
            type: 'TOKEN_OK',
            rid: rid,
            token: token,
            action: msg.action || 'chat_submit',
          }, '*');
        }).catch(function(err) {
          window.postMessage({
            from: 'arena2api-injector',
            type: 'TOKEN_ERR',
            rid: rid,
            error: err.message || String(err),
          }, '*');
        });
        break;

      case 'GET_MODELS':
        var models = extractModels();
        window.postMessage({
          from: 'arena2api-injector',
          type: 'MODELS_OK',
          rid: rid,
          models: models,
        }, '*');
        break;

      case 'GET_COOKIES':
        var cookies = extractCookies();
        window.postMessage({
          from: 'arena2api-injector',
          type: 'COOKIES_OK',
          rid: rid,
          cookies: cookies,
        }, '*');
        break;

      case 'CHECK':
        var g = window.grecaptcha && window.grecaptcha.enterprise
          ? window.grecaptcha.enterprise
          : window.grecaptcha;
        window.postMessage({
          from: 'arena2api-injector',
          type: 'CHECK_OK',
          rid: rid,
          recaptcha: !!(g && typeof g.execute === 'function'),
          enterprise: !!(window.grecaptcha && window.grecaptcha.enterprise),
        }, '*');
        break;

      case 'PROXY_CHAT':
        (function(data, requestId) {
          var prid = data.proxy_id;
          console.log(TAG, 'Proxy chat:', prid, data.model_name);

          getRecaptchaToken('chat_submit').then(function(token) {
            var payload = {
              id: data.eval_id,
              mode: 'direct',
              modelAId: data.model_id,
              userMessageId: data.user_msg_id,
              modelAMessageId: data.model_a_msg_id,
              userMessage: { content: data.prompt, experimental_attachments: [], metadata: {} },
              modality: data.modality || 'chat',
              recaptchaV3Token: token,
            };

            fetch('https://arena.ai/nextjs-api/stream/create-evaluation', {
              method: 'POST',
              headers: { 'Content-Type': 'text/plain;charset=UTF-8' },
              body: JSON.stringify(payload),
              credentials: 'include',
            }).then(function(resp) {
              if (!resp.ok) {
                return resp.text().then(function(t) {
                  window.postMessage({
                    from: 'arena2api-injector', type: 'PROXY_RESULT', rid: requestId,
                    proxy_id: prid, error: true, status: resp.status, body: t,
                  }, '*');
                });
              }
              var reader = resp.body.getReader();
              var decoder = new TextDecoder();
              var content = '', reasoning = '', buf = '';

              function pump() {
                return reader.read().then(function(result) {
                  if (result.done) {
                    window.postMessage({
                      from: 'arena2api-injector', type: 'PROXY_RESULT', rid: requestId,
                      proxy_id: prid, error: false, content: content, reasoning: reasoning,
                    }, '*');
                    return;
                  }
                  buf += decoder.decode(result.value, { stream: true });
                  var lines = buf.split('\n');
                  buf = lines.pop();
                  for (var li = 0; li < lines.length; li++) {
                    var line = lines[li];
                    if (line.indexOf('a0:') === 0) {
                      try { var t = JSON.parse(line.substring(3)); if (typeof t === 'string' && t !== 'hasArenaError') content += t; } catch(e) {}
                    } else if (line.indexOf('ag:') === 0) {
                      try { var t2 = JSON.parse(line.substring(3)); if (typeof t2 === 'string') reasoning += t2; } catch(e) {}
                    }
                  }
                  return pump();
                });
              }
              return pump();
            }).catch(function(err) {
              window.postMessage({
                from: 'arena2api-injector', type: 'PROXY_RESULT', rid: requestId,
                proxy_id: prid, error: true, status: 0, body: err.message || String(err),
              }, '*');
            });
          }).catch(function(err) {
            window.postMessage({
              from: 'arena2api-injector', type: 'PROXY_RESULT', rid: requestId,
              proxy_id: prid, error: true, status: 0, body: 'Token error: ' + (err.message || String(err)),
            }, '*');
          });
        })(msg, rid);
        break;
    }
  });

  // ========== 初始化通知 ==========
  // 延迟一下确保 content.js 已经在监听
  setTimeout(function() {
    var models = extractModels();
    var cookies = extractCookies();
    window.postMessage({
      from: 'arena2api-injector',
      type: 'INIT',
      models: models,
      cookies: cookies,
    }, '*');
    console.log(TAG, 'Injector ready, models:', models ? models.length : 0, 'cookies:', Object.keys(cookies).join(', '));
  }, 1000);

})();
