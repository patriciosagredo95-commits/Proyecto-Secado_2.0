# Sistema de Secado Glover

Base de datos + tablero para los ciclos de las cámaras de secado.

## Cómo se usa

Doble clic en **`Iniciar.bat`**. Se abre el navegador y aparece **una sola página**: arriba
el panel para cargar, abajo el tablero del ciclo. Para detenerlo, cierra la ventana negra.

Para que entren desde otros equipos de la planta, ejecuta **una vez**
`Abrir_en_la_red.bat` con botón derecho → *Ejecutar como administrador*. La dirección de
red aparece al pie del panel de carga y en la ventana negra.

En el panel arrastras los dos archivos del ciclo:

| Archivo | Formato | Nota |
|---|---|---|
| Muestras de humedad | `.xlsx` del Wagner o `.csv` del informe | trae el número de ciclo |
| Programa de secado | `.xlsx` del PLC **o** `.pdf` impreso | el nombre trae la cámara |

El sistema **lee los archivos antes de guardar nada** y te dice qué encontró: número de
ciclo, cámara deducida, cuántas muestras, y los avisos. Recién al apretar *Guardar y ver*
se escribe en la base, y la misma página pasa a mostrar el ciclo recién cargado.

El desplegable **Ciclo en pantalla** cambia entre los ciclos ya guardados. El panel de
carga se pliega con un clic en su título, para presentar sin que estorbe.

## Lo que revisa al cargar

**Cámara.** Un paquete lleva de 24 a 26 tablas y las cámaras 1–2 admiten 24 paquetes
mientras las 3–6 admiten 27. De ahí se deduce en qué cámara cabe la carga. Ojo: la regla
puede *probar* que es una cámara 3–6, pero nunca puede probar que es una 1–2, porque una
carga chica cabe en ambas. En ese caso avisa que es ambigua y eliges tú.

**Duplicados.** Si el total de muestras no cabe ni en la cámara mayor, el archivo trae
más de una carga o el Wagner duplicó los datos. Sale una alerta roja.

**Archivo repetido.** Cada archivo se guarda con su huella `sha256`. Si subes dos veces el
mismo, avisa antes de escribir.

**Precisión.** El PDF impreso trunca cada celda a tres caracteres: el 73 % de los valores
pierde el decimal y las tres columnas de temperatura llegan sin ninguno. El `.xlsx` del
PLC trae la precisión completa. Si tienes los dos, carga el Excel.

## Estructura

```
Sistema/
  Iniciar.bat            arranque
  Abrir_en_la_red.bat    permiso de firewall (una sola vez, como administrador)
  servidor.py            servidor web local
  db.py                  esquema y acceso a SQLite
  ingesta.py             lectores de xlsx / csv / pdf y validaciones
  tablero.py             arma la página desde la base
  plantilla/             fragmentos de la página
  secado.db              la base de datos
  archivos/              copia de cada original cargado
  temp/                  subidas a medio camino
  Logo_Glover.png        (opcional) el logo real; si está, se usa
```

## Base de datos

SQLite, un solo archivo. Cinco tablas: `ciclo`, `proceso` (una fila por minuto),
`muestra` (una fila por tabla medida), `archivo` (trazabilidad de los originales) y
`evento` (bitácora de cargas y alertas).

Para moverla a una carpeta de red, define la variable de entorno antes de arrancar:

```bat
set SECADO_DB=\\servidor\secado\secado.db
set SECADO_ARCHIVOS=\\servidor\secado\archivos
Iniciar.bat
```

## Ponerlo en red

Deja `Iniciar.bat` corriendo en el equipo que haga de servidor y ejecuta una vez
`Abrir_en_la_red.bat` como administrador. Los demás entran con `http://<ip-del-equipo>:8765`
y pueden cargar ciclos desde ahí.

No tiene control de acceso: cualquiera en la red puede cargar y eliminar ciclos. Si va a
quedar expuesto más allá del área de secado, hay que ponerle autenticación.

## Requisitos

Python 3.10 o superior. Sólo usa la biblioteca estándar, salvo `openpyxl` para leer
Excel (ya instalado en este equipo; si faltara: `pip install openpyxl`).
