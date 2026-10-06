const fs = require("fs");

const ITEMS = { 1: { id: 1, name: "owl" } };

function formatItem(item) {
  return { ...item, label: item.name.toUpperCase() };
}

async function findItem(id) {
  return formatItem(ITEMS[id]);
}

function audit(entry) {
  fs.appendFileSync("audit.log", JSON.stringify(entry) + "\n");
}

module.exports = { findItem, audit, formatItem };
