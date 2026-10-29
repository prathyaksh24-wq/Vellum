(function () {
  function clientId(value) {
    return String(value || "")
      .replace(/Agent$/i, "")
      .replace(/[^a-z0-9]+/gi, "")
      .toLowerCase();
  }

  function displayName(value) {
    var base = String(value || "Agent").replace(/Agent$/i, "");
    var spaced = base
      .replace(/([a-z0-9])([A-Z])/g, "$1 $2")
      .replace(/[_-]+/g, " ")
      .replace(/\s+/g, " ")
      .trim();
    return (spaced || "Specialist") + " Agent";
  }

  function placeholder(id, fallbackIcon) {
    return {
      id: clientId(id),
      profileId: String(id || ""),
      name: displayName(id),
      icon: fallbackIcon,
      tag: "Specialized Vellum agent",
      blurb: "A specialist registered with this Vellum installation.",
    };
  }

  function merge(presentationAgents, runtimeAgents, options) {
    var base = Array.isArray(presentationAgents) ? presentationAgents : [];
    if (!Array.isArray(runtimeAgents)) return base.slice();
    var fallbackIcon = options && options.fallbackIcon;
    var byId = new Map(base.map(function (agent) { return [clientId(agent.id), agent]; }));
    return runtimeAgents
      .filter(function (agent) {
        return agent && agent.enabled !== false && agent.status !== "unavailable";
      })
      .map(function (agent) {
        var id = clientId(agent.id || agent.name);
        var known = byId.get(id);
        var fallback = placeholder(agent.name || id, fallbackIcon);
        return Object.assign({}, fallback, known || {}, {
          id: id,
          profileId: String(agent.name || (known && known.profileId) || id),
          name: (known && known.name) || displayName(agent.name || id),
          tag: (known && known.tag) || agent.description || fallback.tag,
          blurb: (known && known.blurb) || agent.description || fallback.blurb,
          icon: (known && known.icon) || fallbackIcon,
        });
      })
      .filter(function (agent) { return !!agent.id; });
  }

  window.VellumUI = window.VellumUI || {};
  window.VellumUI.AgentCatalog = {
    clientId: clientId,
    displayName: displayName,
    merge: merge,
    placeholder: placeholder,
  };
})();
