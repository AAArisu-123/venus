// One-time local QQ Bot onboarding for Venus.
// Prints a QR login URL from Tencent's official connector, then stores the
// returned AppID/AppSecret in ../data/qq-credentials.json (git-ignored).
// The secret is never printed.
import { startQrConnect } from '@tencent-connect/qqbot-connector';
import { mkdirSync, writeFileSync, renameSync, unlinkSync, chmodSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const here = dirname(fileURLToPath(import.meta.url));
const outPath = resolve(here, '..', 'data', 'qq-credentials.json');

function save(appId, appSecret) {
  mkdirSync(dirname(outPath), { recursive: true });
  const tmp = `${outPath}.${process.pid}.tmp`;
  writeFileSync(tmp, JSON.stringify({ app_id: appId, app_secret: appSecret }), { mode: 0o600 });
  try { chmodSync(tmp, 0o600); } catch { /* best effort on Windows */ }
  try {
    renameSync(tmp, outPath);
  } catch (err) {
    try { unlinkSync(tmp); } catch { /* ignore */ }
    throw err;
  }
}

console.log('正在向腾讯申请扫码绑定…');
const stop = startQrConnect({
  onQrDisplayed(url) {
    console.log('');
    console.log('用手机 QQ 打开下面这个链接（或在 QQ 内扫码）并确认授权：');
    console.log(url);
    console.log('');
  },
  onQrExpired() {
    console.log('二维码已过期，正在自动刷新…');
  },
  onSuccess(creds) {
    const [first] = creds;
    if (!first || !first.appId || !first.appSecret) {
      console.error('绑定返回的数据不完整，未保存。');
      process.exit(1);
    }
    save(first.appId, first.appSecret);
    console.log(`绑定成功，凭据已保存到 ${outPath}`);
    console.log('现在可以运行维纳斯了：.venv/Scripts/python.exe -m venus.qq_bot');
    process.exit(0);
  },
  onFailure(err) {
    console.error('绑定失败：' + (err && err.message ? err.message : String(err)));
    process.exit(1);
  },
}, { displayQrCodeToConsole: false, source: 'Venus' });

process.on('SIGINT', () => { stop(); process.exit(130); });
