// カメラ入力の抽象化。UI は CameraSource の3メソッドだけを使う:
//   start(videoEl): Promise<void> / capture(): Promise<Blob> / stop(): void
// 固定カメラ(USB/内蔵) → WebcamSource、テスト → MockSource、手持ち端末 → FileSource。

export class WebcamSource {
  static label = 'Webカメラ（固定カメラ）';
  constructor({ deviceId } = {}) { this.deviceId = deviceId; this.stream = null; this.video = null; }
  static async listDevices() {
    const tmp = await navigator.mediaDevices.getUserMedia({ video: true });   // ラベル取得のため一度許可
    tmp.getTracks().forEach(t => t.stop());
    return (await navigator.mediaDevices.enumerateDevices()).filter(d => d.kind === 'videoinput');
  }
  async start(video) {
    this.stream = await navigator.mediaDevices.getUserMedia({
      video: { deviceId: this.deviceId ? { exact: this.deviceId } : undefined, width: { ideal: 1920 }, height: { ideal: 1080 } },
    });
    this.video = video;
    video.srcObject = this.stream;
    video.hidden = false;
    await video.play();
  }
  async capture() {
    const v = this.video;
    const c = document.createElement('canvas');
    c.width = v.videoWidth; c.height = v.videoHeight;
    c.getContext('2d').drawImage(v, 0, 0);
    return new Promise(res => c.toBlob(res, 'image/jpeg', 0.95));
  }
  stop() { this.stream?.getTracks().forEach(t => t.stop()); this.stream = null; }
}

// カメラ無しで動作確認するための擬似カメラ（毎回少し違う合成画像を返す）
export class MockSource {
  static label = 'テスト用（擬似画像）';
  constructor() { this.canvas = document.createElement('canvas'); this.canvas.width = 960; this.canvas.height = 540; this.n = 0; }
  async start(video) { video.hidden = true; this.video = video; }
  async capture() {
    const c = this.canvas, g = c.getContext('2d');
    g.fillStyle = '#d9dee2'; g.fillRect(0, 0, c.width, c.height);
    this.n++;
    for (let i = 0; i < 3; i++) {
      g.save();
      g.translate(160 + ((this.n * 97 + i * 270) % 640), 120 + ((this.n * 53 + i * 130) % 300));
      g.rotate(((this.n * 31 + i * 57) % 180) * Math.PI / 180);
      g.fillStyle = '#8a959c'; g.fillRect(-110, -9, 220, 18);
      g.beginPath(); g.arc(-110, 0, 22, 0, 7); g.arc(110, 0, 22, 0, 7); g.stroke();
      g.restore();
    }
    return new Promise(res => c.toBlob(res, 'image/jpeg', 0.9));
  }
  stop() {}
}

export class FileSource {
  static label = 'ファイル/端末カメラ（手持ち）';
  async start(video) { video.hidden = true; }
  capture() {
    return new Promise((resolve, reject) => {
      const input = document.createElement('input');
      input.type = 'file'; input.accept = 'image/*'; input.capture = 'environment';
      input.onchange = () => (input.files[0] ? resolve(input.files[0]) : reject(new Error('cancelled')));
      input.click();
    });
  }
  stop() {}
}

export const SOURCES = { webcam: WebcamSource, mock: MockSource, file: FileSource };
