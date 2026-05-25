from operations import add, subtract, multiply, divide

def get_number(prompt):
    while True:
        try:
            return float(input(prompt))
        except ValueError:
            print("Erreur : Veuillez entrer un nombre valide.")

def main():
    print("=== Calculatrice Simple ===")
    print("Opérations disponibles : +, -, *, /")
    print("Tapez 'q' à n'importe quelle étape pour quitter.")

    while True:
        num1_input = input("\nEntrez le premier nombre (ou 'q' pour quitter) : ")
        if num1_input.lower() == 'q':
            print("Au revoir !")
            break
        
        try:
            num1 = float(num1_input)
        except ValueError:
            print("Erreur : Veuillez entrer un nombre valide.")
            continue

        num2_input = input("Entrez le deuxième nombre (ou 'q' pour quitter) : ")
        if num2_input.lower() == 'q':
            print("Au revoir !")
            break
        
        try:
            num2 = float(num2_input)
        except ValueError:
            print("Erreur : Veuillez entrer un nombre valide.")
            continue

        operation = input("Entrez l'opération (+, -, *, /) : ")

        if operation == '+':
            result = add(num1, num2)
        elif operation == '-':
            result = subtract(num1, num2)
        elif operation == '*':
            result = multiply(num1, num2)
        elif operation == '/':
            try:
                result = divide(num1, num2)
            except ValueError as e:
                print(f"Erreur : {e}")
                continue
        else:
            print("Opération invalide. Veuillez utiliser +, -, *, ou /.")
            continue

        print(f"Le résultat de {num1} {operation} {num2} est : {result}")

if __name__ == "__main__":
    main()