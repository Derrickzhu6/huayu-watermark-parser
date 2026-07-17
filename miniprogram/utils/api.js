/** 获取服务器地址 */
function getServerUrl() {
  try {
    var app = getApp();
    return app.globalData.serverUrl || "http://localhost:8000";
  } catch(e) {
    return "http://localhost:8000";
  }
}

/** 视频解析 */
function parseVideo(url) {
  return new Promise(function(resolve, reject) {
    wx.request({
      url: getServerUrl() + "/api/video/parse",
      method: "POST",
      header: { "Content-Type": "application/x-www-form-urlencoded" },
      data: "url=" + encodeURIComponent(url),
      timeout: 30000,
      success: function(res) {
        if (res.data.success) resolve(res.data);
        else reject(new Error(res.data.error || "解析失败"));
      },
      fail: reject
    });
  });
}

/** 图片去水印 */
function uploadAndInpaint(filePath, options) {
  options = options || {};
  return new Promise(function(resolve, reject) {
    var formData = {};
    if (options.useAuto) formData.use_auto = "true";
    if (options.pointsJson) formData.points_json = options.pointsJson;
    if (options.brushRadius) formData.brush_radius = options.brushRadius;
    if (options.radius) formData.radius = options.radius;
    wx.uploadFile({
      url: getServerUrl() + "/api/inpaint",
      filePath: filePath,
      name: "file",
      formData: formData,
      success: function(res) {
        try {
          var data = JSON.parse(res.data);
          if (data.success) resolve(data);
          else reject(new Error(data.error || "处理失败"));
        } catch(e) {
          reject(new Error("服务器返回异常"));
        }
      },
      fail: reject
    });
  });
}

/** 格式转换 */
function convertFile(filePath, format) {
  return new Promise(function(resolve, reject) {
    wx.uploadFile({
      url: getServerUrl() + "/api/convert",
      filePath: filePath,
      name: "file",
      formData: { format: format },
      success: function(res) {
        try {
          var data = JSON.parse(res.data);
          if (data.path) resolve(data);
          else reject(new Error(data.error || "转换失败"));
        } catch(e) {
          reject(new Error("服务器异常"));
        }
      },
      fail: reject
    });
  });
}

/** 下载并保存到相册 */
function downloadAndSave(url) {
  return new Promise(function(resolve, reject) {
    wx.showLoading({ title: "下载中..." });
    wx.downloadFile({
      url: url,
      success: function(res) {
        wx.saveImageToPhotosAlbum({
          filePath: res.tempFilePath,
          success: function() { wx.showToast({ title: "已保存到相册" }); resolve(); },
          fail: function() { reject(new Error("保存失败，请授权相册权限")); }
        });
      },
      fail: reject,
      complete: function() { wx.hideLoading(); }
    });
  });
}

module.exports = { parseVideo: parseVideo, uploadAndInpaint: uploadAndInpaint, convertFile: convertFile, downloadAndSave: downloadAndSave, getServerUrl: getServerUrl };
