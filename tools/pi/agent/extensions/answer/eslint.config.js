import jsdoc from "eslint-plugin-jsdoc";
import tsParser from "@typescript-eslint/parser";

export default [
  {
    ignores: ["node_modules/**", "dist/**"],
  },
  {
    files: ["**/*.ts"],
    languageOptions: {
      parser: tsParser,
      parserOptions: {
        ecmaVersion: "latest",
        sourceType: "module",
      },
    },
    plugins: {
      jsdoc,
    },
    settings: {
      jsdoc: {
        mode: "typescript",
      },
    },
    rules: {
      "jsdoc/require-jsdoc": [
        "error",
        {
          contexts: [
            "FunctionDeclaration",
            "VariableDeclarator > ArrowFunctionExpression",
            "VariableDeclarator > FunctionExpression",
          ],
        },
      ],
      "jsdoc/require-description": "error",
    },
  },
];
