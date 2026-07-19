const app = getApp();
const api = require("../../utils/api");

Page({
  data: { 
    image: "", 
    resultImage: "", 
    brushMode: false, 
    processing: false, 
    brushSize: 8,
    canvasWidth: 300,
    canvasHeight: 150
  },
  brushPts: [],
  canvasCtx: null,
  imgRect: null,
  isDrawing: false,
  origImgWidth: 0,
  origImgHeight: 0,

  onChooseImage() {
    const that = this;
    wx.chooseImage({
      count: 1,
      sizeType: ["original"],
      success: (res) => {
        that.setData({ 
          image: res.tempFilePaths[0], 
          resultImage: "", 
          brushMode: false, 
          processing: false,
          canvasWidth: 300,
          canvasHeight: 150
        });
        that.brushPts = [];
        that.canvasCtx = null;
        that.imgRect = null;
        that.isDrawing = false;
        that.origImgWidth = 0;
        that.origImgHeight = 0;
      }
    });
  },

  // 图片加载后：获取原始尺寸 + 显示尺寸
  onImageLoaded() {
    const that = this;
    // 1. 获取原始图片尺寸
    wx.getImageInfo({
      src: that.data.image,
      success: (info) => {
        that.origImgWidth = info.width;
        that.origImgHeight = info.height;
      }
    });
    // 2. 获取显示尺寸，设置 canvas 大小
    setTimeout(() => {
      wx.createSelectorQuery().in(that)
        .select("#mainImage")
        .boundingClientRect((rect) => {
          if (rect && rect.width > 0 && rect.height > 0) {
            const w = Math.round(rect.width);
            const h = Math.round(rect.height);
            that.imgRect = { left: rect.left, top: rect.top, width: w, height: h };
            that.setData({
              canvasWidth: w,
              canvasHeight: h
            });
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
    this.setData({ brushMode: m });
    this.brushPts = [];
    this.isDrawing = false;
    if (m) {
      const that = this;
      // 确保 imgRect 存在（用 canvas 尺寸兜底）
      if (!that.imgRect || that.data.canvasWidth <= 10) {
        wx.createSelectorQuery().in(that)
          .select("#mainImage")
          .boundingClientRect((rect) => {
            if (rect && rect.width > 0 && rect.height > 0) {
              const w = Math.round(rect.width);
              const h = Math.round(rect.height);
              that.imgRect = { left: rect.left, top: rect.top, width: w, height: h };
              that.setData({ canvasWidth: w, canvasHeight: h });
            }
          }).exec();
      }
      // 等 setData 渲染完成后创建 canvas 上下文
      setTimeout(() => {
        if (that.canvasCtx) return;
        that.canvasCtx = wx.createCanvasContext("brushCanvas", that);
        that.canvasCtx.setStrokeStyle("#e74c3c");
        that.canvasCtx.setLineWidth(that.data.brushSize);
        that.canvasCtx.setLineCap("round");
        that.canvasCtx.setLineJoin("round");
        // 清除旧画布
        that.canvasCtx.clearRect(0, 0, that.data.canvasWidth, that.data.canvasHeight);
        that.canvasCtx.draw();
      }, 100);
    }
  },

  onBrushSizeChange(e) {
    this.setData({ brushSize: e.detail.value });
    if (this.canvasCtx) this.canvasCtx.setLineWidth(e.detail.value);
  },

  onBrushStart(e) {
    if (!this.canvasCtx || !this.imgRect || !this.data.brushMode) return;
    this.isDrawing = true;
    const t = e.touches[0];
    const x = t.x - this.imgRect.left;
    const y = t.y - this.imgRect.top;
    const px = Math.round(x);
    const py = Math.round(y);
    this.brushPts = [{ x: px, y: py }];
    // 在起点画一个点
    this.canvasCtx.beginPath();
    this.canvasCtx.arc(px, py, this.data.brushSize / 2, 0, 2 * Math.PI);
    this.canvasCtx.fillStyle = "#e74c3c";
    this.canvasCtx.fill();
    this.canvasCtx.draw(true);
  },

  onBrushMove(e) {
    if (!this.isDrawing || !this.canvasCtx || !this.imgRect) return;
    const t = e.touches[0];
    const x = t.x - this.imgRect.left;
    const y = t.y - this.imgRect.top;
    const px = Math.round(x);
    const py = Math.round(y);
    const prev = this.brushPts[this.brushPts.length - 1];
    this.brushPts.push({ x: px, y: py });
    this.canvasCtx.beginPath();
    this.canvasCtx.moveTo(prev.x, prev.y);
    this.canvasCtx.lineTo(px, py);
    this.canvasCtx.stroke();
    this.canvasCtx.draw(true);
  },

  onBrushEnd() { 
    this.isDrawing = false; 
  },

  onBrushInpaint() {
    if (!this.data.image || this.brushPts.length < 2) {
      wx.showToast({ title: "请先在图片上涂抹水印区域", icon: "none" });
      return;
    }
    if (this.data.processing) return;
    
    // ===== 核心修复：坐标缩放到原图尺寸 =====
    let scaleX = 1, scaleY = 1;
    if (this.origImgWidth > 0 && this.data.canvasWidth > 0) {
      scaleX = this.origImgWidth / this.data.canvasWidth;
      scaleY = this.origImgHeight / this.data.canvasHeight;
    }
    const scaledPts = this.brushPts.map(pt => ({
      x: Math.round(pt.x * scaleX),
      y: Math.round(pt.y * scaleY)
    }));
    
    this.setData({ processing: true });
    wx.showLoading({ title: "处理中..." });
    api.uploadAndInpaint(this.data.image, {
      pointsJson: JSON.stringify(scaledPts),
      brushRadius: String(Math.round(this.data.brushSize * Math.min(scaleX, scaleY)))
    }).then((res) => {
      this.setData({ resultImage: res.path, brushMode: false });
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
      canvasWidth: 300, canvasHeight: 150
    });
    this.brushPts = [];
    this.canvasCtx = null;
    this.imgRect = null;
    this.isDrawing = false;
  }
});
