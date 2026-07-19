const app = getApp();
const api = require("../../utils/api");

Page({
  data: { 
    image: "", 
    resultImage: "", 
    brushMode: false, 
    processing: false, 
    brushSize: 8
  },
  brushPts: [],
  canvasCtx: null,
  canvasNode: null,
  imgRect: null,
  isDrawing: false,
  origImgWidth: 0,
  origImgHeight: 0,
  canvasReady: false,

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
          processing: false
        });
        that.brushPts = [];
        that.canvasCtx = null;
        that.canvasNode = null;
        that.imgRect = null;
        that.isDrawing = false;
        that.origImgWidth = 0;
        that.origImgHeight = 0;
        that.canvasReady = false;
      }
    });
  },

  onImageLoaded() {
    const that = this;
    // 1. 获取原图实际尺寸
    wx.getImageInfo({
      src: that.data.image,
      success: (info) => {
        that.origImgWidth = info.width;
        that.origImgHeight = info.height;
      }
    });
    // 2. 获取图片显示区域位置和尺寸
    setTimeout(() => {
      wx.createSelectorQuery().in(that)
        .select("#mainImage")
        .boundingClientRect((rect) => {
          if (rect && rect.width > 0 && rect.height > 0) {
            that.imgRect = { 
              left: rect.left, top: rect.top, 
              width: Math.round(rect.width), 
              height: Math.round(rect.height) 
            };
            // 初始化 canvas 尺寸
            that._initCanvas();
          }
        }).exec();
    }, 350);
  },

  _initCanvas() {
    if (!this.imgRect || this.canvasReady) return;
    const that = this;
    wx.createSelectorQuery().in(that)
      .select("#brushCanvas")
      .fields({ node: true, size: true })
      .exec((res) => {
        if (!res || !res[0] || !res[0].node) return;
        const canvas = res[0].node;
        const ctx = canvas.getContext("2d");
        canvas.width = that.imgRect.width;
        canvas.height = that.imgRect.height;
        that.canvasNode = canvas;
        that.canvasCtx = ctx;
        that.canvasReady = true;
      });
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
      // 确保 canvas 已就绪
      if (!that.canvasReady) {
        wx.createSelectorQuery().in(that)
          .select("#mainImage")
          .boundingClientRect((rect) => {
            if (rect && rect.width > 0 && rect.height > 0) {
              that.imgRect = { 
                left: rect.left, top: rect.top, 
                width: Math.round(rect.width), 
                height: Math.round(rect.height) 
              };
              that._initCanvas();
            }
          }).exec();
      }
      // 清除旧画布
      if (that.canvasCtx && that.canvasNode) {
        that.canvasCtx.clearRect(0, 0, that.canvasNode.width, that.canvasNode.height);
      }
    }
  },

  onBrushSizeChange(e) {
    this.setData({ brushSize: e.detail.value });
  },

  onBrushStart(e) {
    if (!this.canvasCtx || !this.imgRect || !this.data.brushMode) return;
    // 确保 canvas 已初始化
    if (!this.canvasReady) this._initCanvas();
    if (!this.canvasCtx) return;
    
    this.isDrawing = true;
    const t = e.touches[0];
    const x = t.x - this.imgRect.left;
    const y = t.y - this.imgRect.top;
    const px = Math.round(x);
    const py = Math.round(y);
    this.brushPts = [{ x: px, y: py }];
    
    // Canvas 2D 绘制
    const ctx = this.canvasCtx;
    ctx.beginPath();
    ctx.strokeStyle = "#e74c3c";
    ctx.lineWidth = this.data.brushSize;
    ctx.lineCap = "round";
    ctx.lineJoin = "round";
    ctx.moveTo(px, py);
    ctx.lineTo(px + 0.1, py + 0.1);
    ctx.stroke();
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
    
    const ctx = this.canvasCtx;
    ctx.beginPath();
    ctx.strokeStyle = "#e74c3c";
    ctx.lineWidth = this.data.brushSize;
    ctx.lineCap = "round";
    ctx.lineJoin = "round";
    ctx.moveTo(prev.x, prev.y);
    ctx.lineTo(px, py);
    ctx.stroke();
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
    
    // 坐标缩放到原图尺寸
    let scaleX = 1, scaleY = 1;
    if (this.origImgWidth > 0 && this.imgRect && this.imgRect.width > 0) {
      scaleX = this.origImgWidth / this.imgRect.width;
      scaleY = this.origImgHeight / this.imgRect.height;
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
      image: "", resultImage: "", brushMode: false, processing: false
    });
    this.brushPts = [];
    this.canvasCtx = null;
    this.canvasNode = null;
    this.imgRect = null;
    this.isDrawing = false;
    this.canvasReady = false;
  }
});
