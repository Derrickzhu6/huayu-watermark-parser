const app = getApp();
const api = require("../../utils/api");

Page({
  data: { 
    image: "", resultImage: "", brushMode: false, processing: false, brushSize: 8,
    canvasWidth: 300, canvasHeight: 150, brushPtsCount: 0
  },
  _pts: [],
  _canvasCtx: null,
  _rect: null,
  _drawing: false,
  _imgW: 0,
  _imgH: 0,

  onChooseImage() {
    const that = this;
    wx.chooseImage({
      count: 1,
      sizeType: ["original"],
      success: (res) => {
        that.setData({ 
          image: res.tempFilePaths[0], resultImage: "", brushMode: false, 
          processing: false, canvasWidth: 300, canvasHeight: 150, brushPtsCount: 0
        });
        that._pts = []; that._canvasCtx = null; that._rect = null;
        that._drawing = false; that._imgW = 0; that._imgH = 0;
      }
    });
  },

  onImageLoaded() {
    const that = this;
    wx.getImageInfo({
      src: that.data.image,
      success: (info) => { that._imgW = info.width; that._imgH = info.height; }
    });
    setTimeout(() => {
      wx.createSelectorQuery().in(that)
        .select("#mainImage")
        .boundingClientRect((rect) => {
          if (rect && rect.width > 0 && rect.height > 0) {
            const w = Math.round(rect.width);
            const h = Math.round(rect.height);
            that._rect = { left: rect.left, top: rect.top, width: w, height: h };
            that.setData({ canvasWidth: w, canvasHeight: h });
          }
        }).exec();
    }, 350);
  },

  onAutoInpaint() {
    if (!this.data.image || this.data.processing) return;
    this.setData({ processing: true });
    wx.showLoading({ title: "处理中..." });
    api.uploadAndInpaint(this.data.image, { useAuto: true, radius: "5" }).then((res) => {
      this.setData({ resultImage: res.path });
      wx.hideLoading();
      wx.showToast({ title: "完成", icon: "success" });
    }).catch((e) => {
      wx.hideLoading();
      wx.showToast({ title: e.message || "处理失败", icon: "none" });
    }).finally(() => { this.setData({ processing: false }); });
  },

  onToggleBrush() {
    const m = !this.data.brushMode;
    this.setData({ brushMode: m, brushPtsCount: 0 });
    this._pts = []; this._drawing = false;
    
    if (m) {
      const that = this;
      if (!that._rect || that.data.canvasWidth <= 10) {
        wx.createSelectorQuery().in(that)
          .select("#mainImage")
          .boundingClientRect((rect) => {
            if (rect && rect.width > 0 && rect.height > 0) {
              const w = Math.round(rect.width);
              const h = Math.round(rect.height);
              that._rect = { left: rect.left, top: rect.top, width: w, height: h };
              that.setData({ canvasWidth: w, canvasHeight: h });
            }
          }).exec();
      }
      setTimeout(() => {
        if (that._canvasCtx) return;
        that._canvasCtx = wx.createCanvasContext("brushCanvas", that);
        that._canvasCtx.setStrokeStyle("#e74c3c");
        that._canvasCtx.setLineWidth(that.data.brushSize);
        that._canvasCtx.setLineCap("round");
        that._canvasCtx.setLineJoin("round");
        that._canvasCtx.clearRect(0, 0, that.data.canvasWidth, that.data.canvasHeight);
        that._canvasCtx.draw();
      }, 100);
    }
  },

  onBrushSizeChange(e) {
    this.setData({ brushSize: e.detail.value });
    if (this._canvasCtx) this._canvasCtx.setLineWidth(e.detail.value);
  },

  onTouchStart(e) {
    if (!this._canvasCtx || !this._rect || !this.data.brushMode) return;
    const that = this;
    // 每次触摸重新查询位置，处理滚动偏移
    wx.createSelectorQuery().in(that)
      .select("#mainImage")
      .boundingClientRect((rect) => {
        if (!rect || rect.width <= 0 || rect.height <= 0) return;
        const w = Math.round(rect.width);
        const h = Math.round(rect.height);
        that._rect = { left: rect.left, top: rect.top, width: w, height: h };
        that._drawing = true;
        const t = e.touches[0];
        // clientX/Y 与 boundingClientRect 都是视口坐标
        const px = Math.round(t.clientX - rect.left);
        const py = Math.round(t.clientY - rect.top);
        that._pts = [{ x: px, y: py }];
        that.setData({ brushPtsCount: 1 });
        // 画起点
        that._canvasCtx.beginPath();
        that._canvasCtx.arc(px, py, that.data.brushSize / 2, 0, 2 * Math.PI);
        that._canvasCtx.fillStyle = "#e74c3c";
        that._canvasCtx.fill();
        that._canvasCtx.draw(true);
      }).exec();
  },

  onTouchMove(e) {
    if (!this._drawing || !this._canvasCtx || !this._rect) return;
    const t = e.touches[0];
    // clientX/Y 与 _rect.left/top 都是视口坐标
    const px = Math.round(t.clientX - this._rect.left);
    const py = Math.round(t.clientY - this._rect.top);
    const prev = this._pts[this._pts.length - 1];
    if (prev && Math.abs(prev.x - px) < 3 && Math.abs(prev.y - py) < 3) return;
    this._pts.push({ x: px, y: py });
    this.setData({ brushPtsCount: this._pts.length });
    // 画线
    this._canvasCtx.beginPath();
    this._canvasCtx.moveTo(prev.x, prev.y);
    this._canvasCtx.lineTo(px, py);
    this._canvasCtx.stroke();
    this._canvasCtx.draw(true);
  },

  onTouchEnd() { this._drawing = false; },

  onBrushSubmit() {
    if (!this.data.image || this._pts.length < 2) {
      wx.showToast({ title: "请先在图片上涂抹水印区域", icon: "none" });
      return;
    }
    if (this.data.processing) return;
    
    let scaleX = 1, scaleY = 1;
    if (this._imgW > 0 && this.data.canvasWidth > 0) {
      scaleX = this._imgW / this.data.canvasWidth;
      scaleY = this._imgH / this.data.canvasHeight;
    }
    const scaledPts = this._pts.map(pt => ({
      x: Math.round(pt.x * scaleX),
      y: Math.round(pt.y * scaleY)
    }));
    
    this.setData({ processing: true });
    wx.showLoading({ title: "处理中..." });
    api.uploadAndInpaint(this.data.image, {
      pointsJson: JSON.stringify(scaledPts),
      brushRadius: String(Math.round(this.data.brushSize * Math.min(scaleX, scaleY)))
    }).then((res) => {
      this.setData({ resultImage: res.path, brushMode: false, brushPtsCount: 0 });
      wx.hideLoading();
      wx.showToast({ title: "完成", icon: "success" });
    }).catch((e) => {
      wx.hideLoading();
      wx.showToast({ title: e.message || "处理失败", icon: "none" });
    }).finally(() => { this.setData({ processing: false }); });
  },

  onSaveImage() {
    if (!this.data.resultImage) return;
    api.downloadAndSave(this.data.resultImage).catch((e) => {
      wx.showToast({ title: e.message || "保存失败", icon: "none" });
    });
  },

  onReset() {
    this.setData({ 
      image: "", resultImage: "", brushMode: false, processing: false,
      canvasWidth: 300, canvasHeight: 150, brushPtsCount: 0
    });
    this._pts = []; this._canvasCtx = null; this._rect = null;
    this._drawing = false; this._imgW = 0; this._imgH = 0;
  }
});
