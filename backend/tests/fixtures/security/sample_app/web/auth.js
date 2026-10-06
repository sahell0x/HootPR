function requireAuth(req, res, next) {
  if (!req.headers.authorization) return res.sendStatus(401);
  return next();
}

module.exports = { requireAuth };
