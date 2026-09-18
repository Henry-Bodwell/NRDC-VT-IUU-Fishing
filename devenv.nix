{
  pkgs,
  lib,
  config,
  inputs,
  ...
}: {
  # https://devenv.sh/packages/
  packages = [
    pkgs.git
    pkgs.poppler-utils
    pkgs.tesseract
  ];

  # https://devenv.sh/languages/
  languages.python = {
    enable = true;
    package = pkgs.python312;
    venv = {
      enable = true;
      requirements = ./requirements.txt;
    };
  };
}
