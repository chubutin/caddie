# Paleta

El cromo viene de la identidad de la **Copa Poletti Classic**
(`~/Downloads/Copa poletti.pdf`), muestreada del PDF:

| | hex | rol |
|---|---|---|
| crema       | `#F8EEE6` | panel en modo claro, tinta en modo oscuro |
| azul marino | `#1E334B` | tinta en modo claro, panel en modo oscuro |
| tostado     | `#C7B9A3` | reglas y bordes |
| salvia      | `#5A6749` | acento (navegación activa) |

Ninguno de los cuatro sirve como color de dato: les falta croma para codificar
series, y el azul marino chocaría con cualquier dato azul. Los datos usan una
familia aparte, validada con `validate_palette.js` contra las superficies
reales donde se dibujan los gráficos (el panel, no la página):

| | claro sobre `#F8EEE6` | oscuro sobre `#1E334B` |
|---|---|---|
| serie 1 | `#B4542A` | `#D9743D` |
| serie 2 | `#00897C` | `#19A091` |
| rampa ordinal | `#DD9158` `#C96A36` `#7C3310` | `#F5C7A8` `#E08A4C` `#A85420` |

Dos ajustes salieron del validador, no del ojo: el teal claro tuvo que subir a
`#00897C` porque a `#00867A` quedaba en croma 0.099 y reprobaba; y el paso más
oscuro de la rampa oscura tuvo que aclararse a `#A85420` porque sobre el azul
Poletti `#8E3F18` daba 1.76:1, bajo el piso de 2:1.

Tipografía: **Lora** para la marca y los títulos (hace eco del logotipo serif
de Poletti), **Archivo** variable para todo el resto y todas las cifras.
