const express = require("express");
const { findItem, audit } = require("./items");
const { requireAuth } = require("./auth");

const app = express();
const router = express.Router();

app.get("/items/:id", async (req, res) => {
  res.json(await findItem(req.params.id));
});

app.delete("/items/:id", requireAuth, removeItem);

router.post("/audit", (req, res) => {
  audit(req.body);
  res.sendStatus(204);
});

app.get("/ping", (req, res) => res.send("pong"));

function removeItem(req, res) {
  audit("delete " + req.params.id);
  res.sendStatus(204);
}

app.use("/api", router);

if (require.main === module) {
  app.listen(3000);
}
