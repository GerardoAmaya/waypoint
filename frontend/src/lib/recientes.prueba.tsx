/**
 * Tests de los itinerarios recordados.
 *
 * Dos riesgos concretos: que localStorage lance —lo hace, no devuelve vacio,
 * cuando el navegador bloquea el almacenamiento— y que lo guardado no sea lo
 * que esperamos. Lo segundo no es hipotetico: ahi queda lo que escribio una
 * version anterior de este mismo codigo, y la lista se pinta en la pantalla de
 * entrada, que es lo primero que ve cualquiera.
 */

import { beforeEach, describe, expect, it, vi } from "vitest";

import {
  CLAVE_RECIENTES,
  CUANTOS,
  leer,
  olvidar,
  recordar,
  type Reciente,
} from "./recientes";

function reciente(extra: Partial<Reciente> = {}): Reciente {
  return {
    codigo: "abc123",
    zona: "Suchitoto",
    dias: 1,
    paradas: 7,
    guardado: "2026-10-21T20:00:00.000Z",
    ...extra,
  };
}

beforeEach(() => {
  window.localStorage.clear();
  vi.restoreAllMocks();
});

describe("recordar y leer", () => {
  it("lo que se guarda se recupera", () => {
    recordar(reciente());
    expect(leer()).toEqual([reciente()]);
  });

  it("el ultimo queda primero", () => {
    recordar(reciente({ codigo: "uno" }));
    recordar(reciente({ codigo: "dos" }));

    expect(leer().map((r) => r.codigo)).toEqual(["dos", "uno"]);
  });

  it("el mismo itinerario sube en vez de duplicarse", () => {
    /**
     * Revisar un dia vuelve a emitir el plan con el mismo codigo. Sin esto, la
     * lista se llenaria de copias del mismo viaje y empujaria afuera a los
     * demas.
     */
    recordar(reciente({ codigo: "uno" }));
    recordar(reciente({ codigo: "dos" }));
    recordar(reciente({ codigo: "uno", paradas: 9 }));

    const lista = leer();
    expect(lista.map((r) => r.codigo)).toEqual(["uno", "dos"]);
    expect(lista[0].paradas).toBe(9);
  });

  it("no crece sin limite", () => {
    for (let i = 0; i < CUANTOS + 4; i++) recordar(reciente({ codigo: `c${i}` }));

    expect(leer()).toHaveLength(CUANTOS);
    expect(leer()[0].codigo).toBe(`c${CUANTOS + 3}`);
  });

  it("sin nada guardado, la lista esta vacia", () => {
    expect(leer()).toEqual([]);
  });
});

describe("olvidar", () => {
  it("saca el que se le pide y deja los demas", () => {
    recordar(reciente({ codigo: "uno" }));
    recordar(reciente({ codigo: "dos" }));

    olvidar("uno");

    expect(leer().map((r) => r.codigo)).toEqual(["dos"]);
  });

  it("olvidar algo que no estaba no rompe nada", () => {
    recordar(reciente({ codigo: "uno" }));
    olvidar("no-existe");

    expect(leer()).toHaveLength(1);
  });
});

describe("lo guardado es entrada externa", () => {
  it("descarta una entrada rota y conserva las sanas", () => {
    /**
     * Una sola malformada no tiene por que borrar las otras. Pintar
     * `reciente.zona` de un objeto sin `zona` revienta la pantalla entera.
     */
    window.localStorage.setItem(
      CLAVE_RECIENTES,
      JSON.stringify([reciente({ codigo: "bueno" }), { codigo: "roto" }, null, 42]),
    );

    expect(leer().map((r) => r.codigo)).toEqual(["bueno"]);
  });

  it("aguanta que no sea JSON", () => {
    window.localStorage.setItem(CLAVE_RECIENTES, "{esto no es json");
    expect(leer()).toEqual([]);
  });

  it("aguanta que sea JSON pero no una lista", () => {
    window.localStorage.setItem(CLAVE_RECIENTES, '{"codigo":"abc"}');
    expect(leer()).toEqual([]);
  });

  it("rechaza numeros que no son numeros", () => {
    window.localStorage.setItem(
      CLAVE_RECIENTES,
      JSON.stringify([{ ...reciente(), dias: "tres" }]),
    );
    expect(leer()).toEqual([]);
  });

  it("recorta una lista mas larga de la cuenta", () => {
    const larga = Array.from({ length: 50 }, (_, i) => reciente({ codigo: `c${i}` }));
    window.localStorage.setItem(CLAVE_RECIENTES, JSON.stringify(larga));

    expect(leer()).toHaveLength(CUANTOS);
  });
});

describe("sin almacenamiento", () => {
  it("leer devuelve vacio en vez de tumbar la pantalla", () => {
    /**
     * En una ventana privada con el almacenamiento bloqueado, getItem lanza.
     * No devuelve null: lanza.
     */
    vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => {
      throw new Error("acceso denegado");
    });

    expect(leer()).toEqual([]);
  });

  it("recordar no lanza aunque no se pueda guardar", () => {
    vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
      throw new Error("sin cuota");
    });

    expect(() => recordar(reciente())).not.toThrow();
  });

  it("olvidar tampoco", () => {
    vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
      throw new Error("sin cuota");
    });

    expect(() => olvidar("abc123")).not.toThrow();
  });
});
