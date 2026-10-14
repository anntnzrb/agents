module Transform

let rotateLeft count values =
    List.skip count values @ List.take count values
