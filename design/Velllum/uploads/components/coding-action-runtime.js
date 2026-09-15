(function () {
  var ACTIONS = {
    "coding.workspace.open": true,
    "github.pull_request.open": true,
    "github.pull_request.create": true,
  };

  function defaultNavigate(navigation) {
    if (!navigation || !navigation.url) return false;
    if (navigation.kind === "external") {
      window.open(navigation.url, "_blank", "noopener,noreferrer");
      return true;
    }
    window.location.assign(navigation.url);
    return true;
  }

  function createRuntime(options) {
    options = options || {};
    var navigate = options.navigate || defaultNavigate;

    function applyReceipt(receipt) {
      if (!receipt || receipt.status !== "applied" || !ACTIONS[receipt.action_id]) return false;
      var navigation = receipt.result && receipt.result.navigation;
      return navigation ? navigate(navigation, receipt) !== false : false;
    }

    return { applyReceipt: applyReceipt };
  }

  window.VellumUI = window.VellumUI || {};
  window.VellumUI.CodingActions = { createRuntime: createRuntime };
})();
