// HootPR review profile for JS/TS (never the repository's eslint config, which is executable code).
// Plugins resolve from /opt/hootpr/configs/node_modules (sandbox/package.json).
import tseslint from "typescript-eslint";
import security from "eslint-plugin-security";
import reactHooks from "eslint-plugin-react-hooks";

export default [
  { ignores: ["**/node_modules/**", "**/dist/**", "**/build/**", "**/*.min.js"] },
  {
    files: ["**/*.{js,jsx,mjs,cjs,ts,tsx}"],
    languageOptions: {
      parser: tseslint.parser,
      parserOptions: { ecmaVersion: "latest", sourceType: "module", ecmaFeatures: { jsx: true } },
    },
    linterOptions: { noInlineConfig: false, reportUnusedDisableDirectives: "off" },
    plugins: { "@typescript-eslint": tseslint.plugin, security, "react-hooks": reactHooks },
    rules: {
      "no-eval": "error",
      "no-implied-eval": "error",
      "no-new-func": "error",
      "no-unsafe-finally": "error",
      "no-unreachable": "warn",
      "no-self-compare": "warn",
      "no-template-curly-in-string": "warn",
      "no-promise-executor-return": "warn",
      "@typescript-eslint/no-unused-vars": "warn",
      "@typescript-eslint/no-explicit-any": "warn",
      "security/detect-eval-with-expression": "error",
      "security/detect-child-process": "warn",
      "security/detect-non-literal-fs-filename": "warn",
      "security/detect-unsafe-regex": "warn",
      "security/detect-possible-timing-attacks": "warn",
      "react-hooks/rules-of-hooks": "error",
      "react-hooks/exhaustive-deps": "warn",
    },
  },
];
