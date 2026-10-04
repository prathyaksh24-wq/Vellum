(function () {
  var client = window.VellumApi.client;
  window.VellumApi.browser = {
    status: function () { return client.request('/api/browser/status', {cache:'no-store'}); },
    frame: function () { return client.request('/api/browser/frame', {cache:'no-store'}); },
    control: function (arguments_, context) {
      return window.VellumApi.appActions.dispatch(
        {action_id:'browser.session.control', action_version:'1', arguments:arguments_},
        Object.assign({source:'ui'}, context || {}, {source:'ui'}),
      ).then(function (receipt) {
        if (receipt.status !== 'applied') throw new Error(receipt.message || 'Browser action failed.');
        return receipt;
      });
    },
    point: function (rect, frame, clientX, clientY) {
      var scale = Math.min(rect.width / frame.width, rect.height / frame.height);
      var x = (clientX - rect.left - (rect.width - frame.width * scale) / 2) / scale;
      var y = (clientY - rect.top - (rect.height - frame.height * scale) / 2) / scale;
      if (x < 0 || y < 0 || x >= frame.width || y >= frame.height) return null;
      return {x:x, y:y};
    },
  };
})();
