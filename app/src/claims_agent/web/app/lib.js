// Punto único de importación del framework (Preact + hooks + htm, un solo archivo local).
// Si algún día se cambia de librería, solo se toca este archivo.
export {
  h, html, render, Component, createContext,
  useState, useReducer, useEffect, useLayoutEffect, useRef, useMemo, useCallback, useContext,
} from "/static/vendor/htm-preact.js";
